# Runbook: the ten-minute Upstash stream test

- **Status:** Ready to run. Not yet run against Upstash.
- **For:** Carlos, who has no Upstash account yet and is new to Redis, so this goes
  slowly on purpose.
- **Why it exists:** ADR 0027 chose Upstash's free plan for the relay's Redis and
  says that choice stands or falls on a test nobody has run. ADR 0029 and ADR 0030
  depend on the same test.
- **Time:** about ten minutes once the account exists, plus a wait for Part C.

## What you are finding out

1. **Does the free plan keep data?** The relay marks an outbox row published once
   Redis has accepted the event. If Redis then forgets it, the event is lost.
2. **Do stream commands count against the monthly allowance like any other
   command?** That budget is why the relay is a batch job and not a loop (ADR 0027).

It also confirms that `XADD`, `XGROUP CREATE`, `XREADGROUP` and `XACK` work over the
Redis protocol on the free plan (ADR 0030), that `XACK` does not delete a message,
and that `MAXLEN ~` trims a stream (ADR 0029).

## Ground rules

- **Never paste a credential into a chat, an issue, a pull request, a commit or a
  file in this repository.** That includes the Redis URL, which contains the
  password. A chat cannot be unsent.
- **Check the free plan's limits yourself** on Upstash's pricing page
  (`https://upstash.com/pricing/redis`) and write down what it says today: monthly
  commands, maximum data size, free databases per account. ADR 0027 quotes 500K
  commands, 256 MB and one database, from a search made on 2026-11-24. Plans change.
- **Every key here starts with `test:`**, so it cannot be confused with the relay's
  real stream, `rag:events`. Delete the test data at the end (Part E).

## About the replies shown here

The replies below are real, but **they come from a local Redis 7.0.15** (started in
this repository's working container, no persistence), not from Upstash. Upstash may
format a reply differently, refuse a command, and will print different message ids.
**A different format is not a failure by itself.** A refused command, or a result
that contradicts "Pass if", is.

A message id such as `1795692802694-0` is a millisecond timestamp, a dash and a
sequence number. Wherever an id appears below, use the ones your own commands printed.

## Part A: set up

### Step 1. Create the account and the database

1. Create an account at `https://upstash.com`. Note whether the free plan asks for a
   payment card. ADR 0025's no-payment constraint matters: a card requirement is a
   finding.
2. Create a **Redis** database, named for example `devtools-rag-test`, on the
   **Free** plan. If it lets you choose a region, pick one in Europe, near Frankfurt
   (ADR 0025).
3. Leave every other option at its default, **and write the defaults down.**
   "Eviction" means the database may delete keys by itself when full, which is
   the thing to be wary of for a stream.
4. Find the connection details: a host, a port and a password, or one URL holding
   all three. All of it is a secret.

### Step 2. Open a way to type commands

**Option 1, the console's command box.** Upstash's console usually has a CLI or
data browser tab. Nothing to install. Easiest for a beginner.

**Option 2, `redis-cli`.** Upstash needs TLS, so the URL starts with `rediss://`
(two s). Read it into a variable without echoing it, so it stays out of your shell
history:

```bash
read -rs UPSTASH_URL
redis-cli --tls -u "$UPSTASH_URL"
```

`--tls` needs `redis-cli` 6 or newer (`redis-cli --version`). If it is older, use
option 1.

### Step 3. Check the connection

```
PING
```

Expected: `PONG`. Fail if the connection is refused, times out or fails to
authenticate. Write down the exact error.

### Step 4. Read the command counter (before)

Find where the console shows commands used this month. **Write the number down**
with the time. Call it `C0`. The counter may lag by a minute or more; note how long.

Redis also has `INFO stats`, which prints `total_commands_processed`. Upstash may
refuse it or not show the line. Try it once and write down what happens. **`INFO`
counts as a command itself**, so read it only before and after.

## Part B: the commands

The stream is `test:events` and the consumer group is `retrieval`, a stand-in for the
retrieval service. In `redis-cli` the replies are printed as shown.

### Step 5. `XADD`: append an event

What the relay does for each outbox row. `*` means "assign a new id".

```
XADD test:events * event_type DocumentIngested payload '{"document_id":"doc-1"}'
```

Expected: a message id.

```
"1795692802694-0"
```

```
XLEN test:events
```

Expected: `(integer) 1`.

Pass if both reply. Fail if `XADD` is refused (unknown command, out of memory,
read-only).

### Step 6. `XGROUP CREATE`: create a consumer group

A consumer group is how a service keeps its place in a stream. `0` means "start from
the beginning", so the group will see `doc-1` too. (`$` would mean "only messages
added from now on".)

```
XGROUP CREATE test:events retrieval 0
```

Expected: `OK`. Then add a second message:

```
XADD test:events * event_type DocumentIngested payload '{"document_id":"doc-2"}'
XLEN test:events
```

Expected: a new id (`"1795692802703-0"`), then `(integer) 2`.

Pass if `OK`. Fail if the command is refused.

### Step 7. `XREADGROUP`: read as a consumer

What retrieval will do. `worker-1` names this consumer inside the group; `>` means
"messages never delivered to anyone in this group".

```
XREADGROUP GROUP retrieval worker-1 COUNT 10 STREAMS test:events >
```

Expected: the stream name, then each message as an id and its fields.

```
1) 1) "test:events"
   2) 1) 1) "1795692802694-0"
         2) 1) "event_type"
            2) "DocumentIngested"
            3) "payload"
            4) "{\"document_id\":\"doc-1\"}"
      2) 1) "1795692802703-0"
         2) 1) "event_type"
            2) "DocumentIngested"
            3) "payload"
            4) "{\"document_id\":\"doc-2\"}"
```

Pass if both messages come back with their fields intact. Run it a second time:
expected `(nil)`, because both were already delivered.

### Step 8. `XPENDING`: read but not yet confirmed

A message read through a group stays "pending" until acknowledged. That is how a
crashed consumer's work is not lost.

```
XPENDING test:events retrieval
```

Expected: the pending count, the lowest and highest pending id, and a count per
consumer.

```
1) (integer) 2
2) "1795692802694-0"
3) "1795692802703-0"
4) 1) 1) "worker-1"
      2) "2"
```

The long form lists one entry per message (id, consumer, milliseconds idle,
delivery count):

```
XPENDING test:events retrieval - + 10
```

Expected: two entries, each with `"worker-1"` and a delivery count of `1`.

Pass if 2 are pending for `worker-1`.

### Step 9. `XACK`: confirm a message

Use the first id your own run printed.

```
XACK test:events retrieval 1795692802694-0
```

Expected: `(integer) 1`. Then `XPENDING test:events retrieval` should report a pending
count of `1`, with both ids now the second message's. Acknowledge the same id again:

```
XACK test:events retrieval 1795692802694-0
```

Expected: `(integer) 0`. A repeated acknowledgement does nothing, which is what
makes it harmless. Acknowledge the second message, then look again:

```
XACK test:events retrieval 1795692802703-0
XPENDING test:events retrieval
```

Expected: `(integer) 1`, then

```
1) (integer) 0
2) (nil)
3) (nil)
4) (nil)
```

Pass if the counts go 2, 1, 0 and the repeat returns `0`.

### Step 10. `XLEN` after `XACK`: nothing was deleted

The check behind ADR 0029.

```
XLEN test:events
```

Expected: `(integer) 2`.

**This is the surprising one.** Both messages were read and acknowledged and both are
still in the stream. `XACK` only clears the group's pending record. Only trimming
removes messages, which is why the relay bounds the stream. Pass if `2`. If it is
`0`, ADR 0029's premise is wrong on Upstash.

### Step 11. `XADD ... MAXLEN ~`: trimming

ADR 0029 has the relay add every message with `MAXLEN ~ 100000`. You cannot add that
many by hand, so this step uses a bound of 100. Know two things first, both seen on
the local Redis:

- `MAXLEN 100` trims exactly. `MAXLEN ~ 100` lets the server trim in whole internal
  blocks (about 100 entries each), so it keeps *at least* 100 and may sit a little
  above.
- On a **small** stream, `~` trims **nothing**: eight messages added with
  `MAXLEN ~ 3` all stayed. Do not call trimming broken from a test that small.

Add 300 messages with a bound of 100. From a normal terminal, not inside the
`redis-cli` prompt:

```bash
redis-cli --tls -u "$UPSTASH_URL" DEL test:events
for i in $(seq 1 300); do
  echo "XADD test:events MAXLEN ~ 100 * event_type DocumentIngested payload n$i"
done | redis-cli --tls -u "$UPSTASH_URL" > /dev/null
redis-cli --tls -u "$UPSTASH_URL" XLEN test:events
```

If you are using the console's command box, paste a few dozen `XADD` lines instead
and say so in your notes. Expected: **about 100, not 300.** Locally it was exactly
`(integer) 100`, and one more such `XADD` made it `101`. Anything from 100 to a few
hundred shows trimming; 300 means none.

Then the exact form:

```
XADD test:events MAXLEN 3 * event_type DocumentIngested payload last
XLEN test:events
```

Expected: an id, then `(integer) 3`.

Pass if `~` leaves far fewer than 300 and exact `MAXLEN` leaves 3. Fail if neither
trims or the option is refused.

## Part C: persistence

The commands above cannot answer this, and **this runbook does not claim to know the
answer for Upstash.** It lists what to observe.

```
XADD test:keep * event_type DocumentIngested payload '{"document_id":"keep-1"}'
```

Write down the id and the time. Then:

1. **Reconnect.** Close the client, open it again, run `XRANGE test:keep - +`. The
   message should still be there. This is the weak test, because a server that merely
   stays up passes it.
2. **Wait.** Come back after several hours, ideally after a night, and run
   `XRANGE test:keep - +` again. Look for the same id and fields.
3. **Read what Upstash says** about durability, persistence and data loss on the free
   plan. Quote its wording in your notes, and look for any mention of eviction, or of
   a database being paused or archived after inactivity.
4. **Look in the console** for a size or key limit, and for the stream's memory use if
   it is shown.

If the message is gone after the wait, that is a fail, however the plan describes
itself.

## Part D: the command counter

1. **Read the counter again** (a few minutes after Part B, since it may lag). Call it
   `C1`.
2. **Count what you ran**: every command you typed, including `PING`, each `INFO` and
   the 301 in step 11 (the `DEL` and 300 `XADD`s). Call the total `N`.
3. **Compare `C1 - C0` with `N`.**

What to look for:

- **Close to `N`:** one command counts as one, and stream commands are not special.
- **Much larger:** one command is being counted several times. Isolate it: note the
  counter, run that one command once, note it again. `XREADGROUP` is the one to isolate.
- **Smaller:** the console may lag or count only some commands. Note it.

Run the isolation with nothing else open on the database; the web console may send
commands of its own. For reference, locally one `XADD`, one `XGROUP CREATE` and one
`XREADGROUP` each raised `total_commands_processed` by exactly one, and so did the
`INFO` that read it.

## Part E: clean up

After Part C's wait is done:

```
DEL test:events test:keep
```

Expected: `(integer) 2` (the group goes with the stream).

## Pass and fail

| # | Check | Pass | Fail |
|---|---|---|---|
| 1 | Sign-up | Free database, no card required | A card or paid plan is required |
| 2 | Connection | `PING` replies `PONG` over TLS | Refused, times out or cannot authenticate |
| 3 | `XADD` | Replies with an id | Refused or errors |
| 4 | `XGROUP CREATE` | `OK` | Refused or errors |
| 5 | `XREADGROUP` | Both messages with fields intact; the second read is `(nil)` | Refused, or fields missing or altered |
| 6 | `XPENDING`, `XACK` | Counts go 2, 1, 0; a repeated `XACK` returns 0 | Wrong counts or refused |
| 7 | `XACK` does not delete | `XLEN` is still 2 | `XLEN` is 0: ADR 0029's premise is wrong |
| 8 | Trimming | `MAXLEN ~ 100` leaves far fewer than 300; `MAXLEN 3` leaves 3 | Neither trims, or refused |
| 9 | Persistence, reconnect | Same message after reconnecting | Message gone |
| 10 | Persistence, wait | Same id and fields after the wait | Gone, or the database was paused or archived |
| 11 | Command counting | `C1 - C0` close to `N` | A stream command is counted several times, so the 500K budget does not hold |
| 12 | Plan limits | At least what ADR 0027 quotes | Lower: recompute ADR 0027's budget and ADR 0029's bound |

Rows 2 to 8 are the protocol check (ADR 0030). Rows 9 to 11 are the two things ADR
0027 says it did not verify. A fail in 9, 10 or 11 sends the choice to its fallback.

## What to write down

In a file outside the repository, **never including the URL, password or a token**:

- Date and time of the run, region, and plan name.
- The pricing page numbers, and whether a card was asked for.
- The defaults you left alone, eviction above all.
- Every reply that differs from the ones here, and every refused command with its
  exact error text.
- `C0`, `C1`, `N`, and how long the counter took to move. What `INFO stats` said.
- Persistence: when you added the message, when you checked, and what you saw. Upstash's
  own durability wording, quoted.

## Recording the result

By **correcting the ADRs in place** in a normal pull request (`docs/COLLABORATION.md`
section 8), not by adding a record that supersedes them.

- **ADR 0027:** replace the "Not verified" paragraph with what was verified, the date
  and what was seen. If row 9, 10 or 11 failed, correct "Where Redis lives" and move
  to the fallback.
- **ADR 0029:** correct the `XACK` sentence to say it was also checked on Upstash, or
  what differed; update the plan limits and, if they changed, the sizing of 100000.
- **ADR 0030:** replace the "depends on the Upstash test" sentences with the outcome.
  If the protocol failed, the REST path applies.

If anything failed, stop and tell the reviewer first: a failed row changes a decision,
not only a sentence.

## If something goes wrong

- **`NOAUTH` or authentication errors.** The password is missing from the URL. Copy
  it again from the console.
- **A TLS error.** The URL must start with `rediss://` and `--tls` must be given.
- **`ERR unknown command`.** Upstash does not support it on your plan. That is a
  finding, and the most important kind.
- **`WRONGTYPE`.** The key already exists and is not a stream. `DEL` it and redo the step.
- **`BUSYGROUP`.** You ran `XGROUP CREATE` twice. Harmless.
