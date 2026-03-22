# zmail API Help

- **mode**: read_only
- **description**: Gmail API. All actions are read-only.

## Actions

### help
Show available actions and required parameters.

### getInbox
Return list of threads in your mailbox.
- `page`: Optional. Integer >= 1. Default: 1.
- `perPage`: Optional. Integer between 5 and 20. Default: 5.

### getThread
Return rowID and messageID list for a selected thread. No message body.
- `threadID`: Required. Numeric thread identifier.

### getMessages
Return one or more messages by rowID/messageID (hash).
- `ids`: Required. Numeric rowID, 32-char messageID, or an array of them.

### search
Search messages with full-text style query and Gmail-like operators.
- `query`: Required. Supports words, "phrase", -exclude, from:, to:, subject:, subject:"phrase", subject:(phrase), OR, AND. Missing operator means AND.
- `page`: Optional. Integer >= 1. Default: 1.
- `perPage`: Optional. Integer between 5 and 20. Default: 5.

### reset
Reset request counter for this apikey in memcache.
