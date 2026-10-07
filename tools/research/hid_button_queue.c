/* Authored, freestanding reference core; no USB, flash or peripheral operations.
 * Firmware adapter must serialize access and provide transport completion/reset.
 * Storage may live in the retired mapper body; no hidden libc/BSS dependency.
 */
typedef unsigned char u8;
typedef unsigned int u32;
struct hid_queue {
    u8 pending[8], head, count, active, phase, inflight, valid, fault, dropped;
};
_Static_assert(sizeof(struct hid_queue) <= 32, "bounded firmware scratch");

void hid_queue_reset(struct hid_queue *q) {
    u8 *p = (u8 *)q;
    for (u32 i = 0; i < sizeof(*q); ++i) p[i] = 0;
}

u8 hid_button_action(u32 key, u32 event) {
    if (key == 2) {
        if (event == 7) return 4;
        if (event == 8) return 8;
        if (event == 9) return 16;
        if (event == 5) return 32;
    } else if (key == 4) {
        if (event == 7) return 1;
        if (event == 5) return 8;
    } else if (key == 8) {
        if (event == 7) return 2;
        if (event == 5) return 16;
    }
    return 0;
}

int hid_queue_event(struct hid_queue *q, u32 key, u32 event) {
    u8 mask = hid_button_action(key, event);
    if (!mask || q->fault) return 0;
    if (q->count + (q->active != 0) >= 8) {
        if (q->dropped != 255) ++q->dropped;
        return 0;
    }
    q->pending[(q->head + q->count) & 7] = mask;
    ++q->count;
    return 1;
}

/* Returns 1 and a stable three-byte report only if submission is possible. */
int hid_queue_submit(struct hid_queue *q, u8 report[3]) {
    if (q->fault || q->valid) return 0;
    if (!q->phase) {
        if (!q->count) return 0;
        q->active = q->pending[q->head];
        q->head = (q->head + 1) & 7;
        --q->count;
        q->phase = 1;
    }
    q->inflight = q->phase == 1 ? q->active : 0;
    q->valid = 1;
    report[0] = 1; report[1] = q->inflight; report[2] = 0;
    return 1;
}

void hid_queue_not_accepted(struct hid_queue *q) { q->valid = 0; }

int hid_queue_complete(struct hid_queue *q, u32 mask, u32 error) {
    if (!q->valid || mask != q->inflight) return 0;
    q->valid = 0;
    if (error) { q->fault = 1; return 1; }
    if (q->phase == 1) q->phase = 2;
    else { q->phase = 0; q->active = 0; }
    return 1;
}
