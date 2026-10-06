FROM python:3.13-alpine
RUN apk add --no-cache openssh-client ca-certificates
WORKDIR /app
COPY app.py /app/app.py
RUN addgroup -S healer && adduser -S -G healer healer \
    && mkdir -p /var/lib/healer && chown healer:healer /var/lib/healer
USER healer
EXPOSE 8080
ENTRYPOINT ["python", "/app/app.py"]
