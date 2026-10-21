# Nightly encrypted backups and the restore drill (docs/03-operations.md).
# Postgres client tools of the same major version as the server, age for
# encryption, rclone for any S3-compatible bucket.
FROM postgres:17.11-alpine
RUN apk add --no-cache age rclone tini su-exec
COPY backup.sh restore-drill.sh /usr/local/bin/
# Remotes come from RCLONE_CONFIG_* variables: no config file.
ENV RCLONE_CONFIG=/dev/null
RUN chmod +x /usr/local/bin/backup.sh /usr/local/bin/restore-drill.sh
ENTRYPOINT ["/sbin/tini", "--"]
CMD ["backup.sh", "schedule"]
