# Backup with validation

A backup that is not validated is a belief. A backup that reports success
without validating is worse - it converts an unknown into a false certainty.

**Four copies of this pattern once existed side by side. One validated. Three
did not**, and reported success on an unverified path.

---

## The shape

```bash
STAMP=$(date +%Y%m%d-%H%M%S)
STAGING="/tmp/${PROFILE}-backup-${STAMP}"
REMOTE_DIR="${BACKUP_PATH}/backup-${STAMP}"

# 1. required config aborts, it does not default
[ -z "${BACKUP_HOST:-}" ] && { echo "[ERROR] BACKUP_HOST not set"; exit 1; }

# 2. create the archive
sudo tar czf "$STAGING/data.tar.gz" -C /var/lib "$PROFILE"

# 3. transfer, recording WHICH path ran
if rsync -a "$STAGING/" "${BACKUP_USER}@${BACKUP_HOST}:${REMOTE_DIR}/"; then
    METHOD=rsync
else
    echo "[WARN] rsync failed, falling back to tar over ssh"
    tar cf - -C "$STAGING" . | ssh "${BACKUP_USER}@${BACKUP_HOST}" "mkdir -p '$REMOTE_DIR' && tar xf - -C '$REMOTE_DIR'"
    METHOD=tar-ssh
fi

# 4. VALIDATE - the load-bearing step
REMOTE_SIZE=$(ssh "${BACKUP_USER}@${BACKUP_HOST}" "du -sb '$REMOTE_DIR' | cut -f1")
if [ -z "$REMOTE_SIZE" ] || [ "$REMOTE_SIZE" -lt "$MIN_EXPECTED_BYTES" ]; then
    echo "[ERROR] Backup at $REMOTE_DIR is missing or too small ($REMOTE_SIZE bytes)"
    notify_failure "backup validation failed for $PROFILE"
    exit 1
fi

ssh "${BACKUP_USER}@${BACKUP_HOST}" "tar tzf '$REMOTE_DIR/data.tar.gz' > /dev/null" || {
    echo "[ERROR] Archive at $REMOTE_DIR is not readable"
    notify_failure "backup archive unreadable for $PROFILE"
    exit 1
}

echo "[OK] Backup verified at $REMOTE_DIR via $METHOD ($REMOTE_SIZE bytes)"
```

---

## Load-bearing

### Step 4 exists at all

Steps 1 to 3 can all succeed while nothing usable arrives. `rsync` returning
non-zero, a fallback that silently writes an empty directory, a `tar` that
produced a zero-byte archive - none of these are visible without reading back
what landed.

**Validate remotely, not locally.** Checking the staging directory proves the
archive was built, not that it transferred.

### `$METHOD` is recorded and reported

A degraded path that works is fine. A degraded path nobody knows is running is
how a backup silently changes character for two weeks.

One copy's rsync failed on every run and fell back, and the success message
was identical either way.

### Failure is notified, not just logged

A log file on a machine nobody logs into is not a notification. See
`patterns/README.md` - this is the same class as the deploy pipeline reporting
`deploy finished` for a crash-looping container.

### Absence of a backup is also a failure

A backup that never runs produces no output at all, and silence reads as
success. Freshness must be checked by something that is **not the machine being
backed up** - the observer must not share fate with the observed.

---

## Restore

Every backup needs a restore path, and the restore must have been **run at
least once**. A backup script with no restore script is discovered only when it
is needed.

An untested restore is an assumption about file layout, permissions, and
service state, all of which drift.

---

## Known wrong

Three copies identical to the above through step 3, then straight to the
success message. A fourth gained validation later and the others never did.

The remedy is not three patches. Four clones will drift again - extract to a
shared helper.
