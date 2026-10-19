#!/bin/sh
# certbot продлевает сертификаты в общем томе; nginx перечитывает их раз в 6 ч (глава 26).
(while sleep 21600; do nginx -s reload; done) &
