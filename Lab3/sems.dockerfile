FROM debian:13

ENV DEBIAN_FRONTEND=noninteractive

RUN apt update
RUN apt install -y \
         git debhelper g++ make libspandsp-dev flite1-dev \
         libspeex-dev libgsm1-dev libopus-dev libssl-dev python3-dev \
         python3-pip libev-dev \
         openssl libev-dev libmysqlcppconn-dev libevent-dev \
         libxml2-dev libcurl4-openssl-dev libhiredis-dev

RUN apt install -y devscripts libbcg729-dev
RUN pip install sip --break-system-packages
WORKDIR /

RUN git clone --depth 1 --branch master https://github.com/sems-server/sems.git

WORKDIR /sems
RUN make install
RUN mkdir /var/local/run

CMD ["/usr/local/sbin/sems", "-E", "-f", "/usr/local/etc/sems/sems.conf"]

