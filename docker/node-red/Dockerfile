FROM nodered/node-red:5.0.9

RUN npm install --omit=dev --no-audit --no-fund \
    node-red-contrib-iot-controlcenter@2.2.1 \
    node-red-node-mysql@3.0.4

USER root
RUN mkdir -p /config && chown node-red:node-red /config
COPY docker/node-red/registration.js /usr/src/node-red/registration.js
USER node-red
