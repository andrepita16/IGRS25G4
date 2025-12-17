import sys
import KSR as KSR # type: ignore

import sqlite3
import os

# Caminho para a BD (garante que a pasta tem permissoes de escrita)
DB_PATH = "/tmp/redial_service.db"

def db_init():
    with sqlite3.connect(DB_PATH) as conn:
        # Cria a tabela se nao existir
        conn.execute('''CREATE TABLE IF NOT EXISTS user_redial 
                        (user TEXT PRIMARY KEY, targets TEXT)''')
        conn.commit()

def db_save_list(user, targets_list):
    # Guarda a lista como uma string separada por virgulas
    targets_str = ",".join(targets_list)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("REPLACE INTO user_redial (user, targets) VALUES (?, ?)", 
                     (user, targets_str))
        conn.commit()

def db_get_list(user):
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute("SELECT targets FROM user_redial WHERE user=?", (user,))
        row = cursor.fetchone()
        if row and row[0]:
            return row[0].split(",") # Devolve lista ["sip:a", "sip:b"]
    return []

def db_clear_list(user):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("DELETE FROM user_redial WHERE user=?", (user,))
        conn.commit()

# Inicializa a BD no arranque
db_init()
MAX_REDIALS = 5
# Mandatory function - module initiation
def mod_init():
    KSR.info("===== from Python mod init\n")
    return kamailio()

class kamailio:
    # Mandatory function - Kamailio class initiation
    def __init__(self):
        KSR.info('===== kamailio.__init__\n')

    # Mandatory function - Kamailio subprocesses
    def child_init(self, rank):
        KSR.info('===== kamailio.child_init(%d)\n' % rank)
        return 0

    # Function called for REQUEST messages received 
    def ksr_request_route(self, msg):
        
        #  TRATAMENTO DO REGISTER / DEREGISTER ("Redial 2.0")
        if msg.Method == "REGISTER":
            # 1. Verificar Domínio (Requisito: Apenas acme.operador)
            # 
            domain = KSR.pv.get("$td") # Domínio do To
            if domain != "acme.operador":
                KSR.info(f"REGISTO RECUSADO: Dominio invalido {domain}\n")
                KSR.sl.send_reply(403, "Forbidden - Apenas acme.operador permitido")
                return 1

            # 2. Verificar se é De-registo (Expires == 0)
            is_deregister = False
            exp_hdr = KSR.hdr.get("Expires")
            if exp_hdr is not None and int(exp_hdr) == 0:
                is_deregister = True                                       
            rc = KSR.registrar.save('location', 0)
            
            if rc < 0:
                KSR.info("Erro ao salvar registo\n")
                KSR.sl.send_reply(500, "Server Error")
                return 1
            
            user_aor = KSR.pv.get("$tu")

            if is_deregister:
                # [cite: 309, 316] "O de-registo... implica a eliminação da sua lista"
                KSR.info(f"DEREGISTER detetado para {user_aor}. A limpar lista de redial...\n")
                # TODO: Chamar função para limpar BD: db_clear_redial_list(user_aor)               
            else:
                KSR.info(f"REGISTER detetado para {user_aor}. A inicializar lista de redial...\n")
                # TODO: Chamar função para init BD: db_init_redial_list(user_aor)

            return 1
               
        # ... (dentro de ksr_request_route) ...

        if (msg.Method == "INVITE"):                      
            KSR.info("INVITE recebido. From: " + KSR.pv.get("$fu") + " To: " + KSR.pv.get("$tu") + "\n")
            
            # Verificar se o destinatário está registado
            if KSR.registrar.lookup("location") != 1:
                KSR.sl.send_reply(404, "User Not Found")
                return 1

            # --- LÓGICA REDIAL 2.0 (Ponto 1 e 2) ---
            caller_aor = KSR.pv.get("$fu") 
            callee_aor = KSR.pv.get("$tu") 

            # 1. Obter a lista da Base de Dados
            # Isto agora funciona mesmo se for outro processo a tratar o INVITE
            user_targets = db_get_list(caller_aor)
            
            is_redial_target = False
            # Verifica se o destino está na lista recuperada da BD
            if callee_aor in user_targets:
                is_redial_target = True

            if is_redial_target:
                KSR.info(f"[REDIAL] Alvo detetado na BD. A monitorizar {caller_aor} -> {callee_aor}\n")
                KSR.pv.sets("$avp(retries_left)", str(MAX_REDIALS))
                KSR.tm.t_on_failure("ksr_failure_redial")
            else:
                KSR.info(f"[REDIAL] Chamada normal. Lista do utilizador: {user_targets}\n")

            KSR.rr.record_route()
            KSR.tm.t_relay()
            return 1



        if (msg.Method == "ACK"):
            KSR.rr.loose_route()
            KSR.tm.t_relay()
            return 1

        if (msg.Method == "BYE"):
            KSR.rr.loose_route()
            KSR.tm.t_relay()
            return 1

        if (msg.Method == "CANCEL"):
            KSR.rr.loose_route()
            KSR.tm.t_relay()
            return 1
        
        if msg.Method == "MESSAGE":
            ruri = KSR.pv.get("$ru")
            if "sip:redial@" not in ruri:
                KSR.info(f"MESSAGE rejeitado (destino desconhecido): {ruri}\n")
                KSR.sl.send_reply(404, "Não foi encontrado - Use sip:redial@acme.operador")
                return 1
            
            sender_aor = KSR.pv.get("$fu")
            body = KSR.pv.get("$rb")
            if not body:
                KSR.sl.send_reply(400, "Corpo Vazio")
                return 1
            KSR.info(f"REDIAL MSG de {sender_aor}: {body}\n")
            parts = body.strip().split()
            command = parts[0].upper()
            if command == "ACTIVATE":
                if len(parts) < 2:
                    KSR.sl.send_reply(400, "Mau Pedido")
                    return 1
                targets = parts[1:]
                clean_targets = []
                for t in targets:
                    if "sip:" not in t:
                       t = f"sip:{t}@{KSR.pv.get('$td')}"
                    clean_targets.append(t)
                
                db_save_list(sender_aor, clean_targets)
                
                KSR.info(f"REDIAL ATIVO (BD) para {sender_aor}. Lista: {clean_targets}\n")
                KSR.sl.send_reply(200, f"OK - Service Activated")
                return 1

            elif command == "DEACTIVATE":
                # [ALTERAÇÃO AQUI] Limpar na BD
                db_clear_list(sender_aor)
                
                KSR.info(f"REDIAL DESATIVADO (BD) para {sender_aor}\n")
                KSR.sl.send_reply(200, "OK - Service Deactivated")
                return 1
            else:
                KSR.sl.send_reply(400, "Comando desconhecido")
                return 1

            
        return 1

    # Function called for REPLY messages received
    def ksr_reply_route(self, msg):
        KSR.info("===== reply_route - from kamailio python script: ")
        KSR.info("  Status is:"+ str(KSR.pv.get("$rs")) + "\n")
        return 1

    # Function called for messages sent/transit
    def ksr_onsend_route(self, msg):
        KSR.info("===== onsend route - from kamailio python script:")
        KSR.info("   %s\n" %(msg.Type))
        return 1
    
    # ==========================================================
    #  FAILURE ROUTE - Lógica de Remarcação Automática
    # ==========================================================
    def ksr_failure_redial(self, msg):
        KSR.info("[REDIAL-FAIL] Failure route acionada.\n")

        # Verifica códigos: 486 (Busy), 408 (Timeout), 480 (Temp. Unavailable)
        if KSR.tm.t_check_status("486|408|480"):
            
            # Ler tentativas restantes da variável
            retries_val = KSR.pv.get("$avp(retries_left)")
            
            # Converter para int de forma segura
            if retries_val is not None:
                retries = int(retries_val)
            else:
                retries = 0
            
            if retries > 0:
                KSR.info(f"[REDIAL-LOGIC] Falha. Tentativas: {retries}. A remarcar...\n")
                
                # 1. Decrementar contador
                next_retries = str(retries - 1)
                KSR.pv.sets("$avp(retries_left)", next_retries)
                
                # 2. Re-armar a failure route para a próxima tentativa
                # (Se esta nova tentativa falhar, queremos voltar aqui)
                KSR.tm.t_on_failure("ksr_failure_redial")
                
                # --- A MAGIA (Workaround sem corex) ---
                
                # 3. Restaurar o R-URI para o destino original ($tu - To URI)
                # Isto "limpa" o estado de erro e define para onde queremos ligar de novo
                original_dst = KSR.pv.get("$tu")
                KSR.pv.sets("$ru", original_dst)
                
                # 4. Voltar a descobrir a localização (IP/Porta) do utilizador
                # Como estamos a "recomeçar", precisamos de saber onde ele está registado
                KSR.registrar.lookup("location")
                
                # 5. Enviar novamente
                # Agora o t_relay já não se queixa de "no branches" porque
                # alterámos o R-URI e fizemos lookup, criando um novo destino válido.
                KSR.tm.t_relay()
                
                return 1
            else:
                KSR.info("[REDIAL-LOGIC] Limite de tentativas atingido. A desistir.\n")
                return 1
        
        return 1
