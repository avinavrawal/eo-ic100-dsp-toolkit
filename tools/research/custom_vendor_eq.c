/* Offline-authored extension. No flash, programmer, reboot or memory commands.
 * Addresses are specific to SHA-verified Samsung 0.23 B. AAPCS Thumb softfp.
 */
typedef unsigned char u8;
typedef unsigned short u16;
typedef unsigned int u32;
struct setup { u8 type, request; u16 value, index, length; };
struct vendor { const struct setup *setup; const u8 *payload; u16 length, pad; };
struct frame { u8 state, reserved[3]; const u8 *payload; u16 length, pad; struct setup setup; };
struct band { u32 type; float gain, frequency, q; };
struct eq { float left, right; u32 count; struct band bands[8]; };
struct caps { u8 magic[4]; u16 version, bands; u32 flags; };
_Static_assert(sizeof(struct setup)==8, "setup ABI");
_Static_assert(__builtin_offsetof(struct frame,setup)==12, "frame ABI");
_Static_assert(__builtin_offsetof(struct vendor,length)==8, "vendor ABI");

#ifndef ENABLE_EQ_TEST
#define ENABLE_EQ_TEST 0
#endif
#ifndef GUARD_TRACE
#define GUARD_TRACE 0
#endif

#if GUARD_TRACE
/* E2 guard trace lives in the diagnostic overlay's reserved RX tail. Two
 * event bits per predicate: evaluated, then passed. This records the actual
 * branch-time values without re-reading state or changing branch order. */
#define GUARD_TRACE_EVENTS (*(volatile u32 *)0x200198c0)
#define GUARD_EVAL(n) (1u << (10u + 2u*(n)))
#define GUARD_PASS(n) (1u << (11u + 2u*(n)))
#define TRACE_GUARD(n,ok) do { GUARD_TRACE_EVENTS |= GUARD_EVAL(n); \
    if (ok) GUARD_TRACE_EVENTS |= GUARD_PASS(n); } while (0)
#else
#define TRACE_GUARD(n,ok) do { (void)(ok); } while (0)
#endif
/* Keep the physically validated CAPS response byte-for-byte identical in both
 * variants; this flag field remains zero and is not a mutation capability bit. */
static const struct caps capabilities = {{'E','O','I','C'},1,8,0};
static int custom(const struct setup *s) {
    return (s->type & 0x60)==0x40 && (s->request==0xe0 || s->request==0xe1);
}
static int format(const struct setup *s) {
    if (s->value != 0x454f || s->index != 0x4943) return 0;
    if (s->request==0xe0) return s->type==0xc0 && s->length==12;
    return ENABLE_EQ_TEST && s->type==0x40 && s->length==4;
}

__attribute__((used)) int eoic_setup(struct frame *f) {
    if (custom(&f->setup) && !format(&f->setup)) return 0;
    return ((int (*)(struct frame *))0x0020dd11)(f);
}

/* Bitwise finite check avoids libc and catches signaling/quiet NaNs. */
static int finite(float f) {
    union { float f; u32 u; } v={f};
    return (v.u & 0x7f800000) != 0x7f800000;
}

__attribute__((used)) int eoic_valid_eq(const struct eq *p, u32 rate) {
    if (rate < 32000 || rate > 192000 || p->count==0 || p->count>8) return 0;
    if (!finite(p->left) || !finite(p->right) || p->left < -12 || p->left > 0 ||
        p->right < -12 || p->right > 0) return 0;
    for (u32 i=0;i<p->count;++i) {
        const struct band *b=&p->bands[i];
        if (b->type>4 || !finite(b->gain) || b->gain < -12 || b->gain > 6 ||
            !finite(b->frequency) || b->frequency < 20 || b->frequency >= (float)(rate/2) ||
            !finite(b->q) || b->q < 0.1f || b->q > 16) return 0;
    }
    return 1;
}

#if ENABLE_EQ_TEST
/* The stock setter's two acknowledgement loops have no timeout. These tiny
 * naked helpers are called through local Thumb literal trampolines inserted
 * at those loops. They preserve the stock caller registers on success, return
 * r3=0x200162b4 on acknowledgement / r3=0 on timeout. The finite limit is
 * 65,535 MMIO reads. On timeout, bit 22 is restored to the currently observed
 * bit 24 and the stock update-busy byte is cleared. Success toggles the same
 * software bank byte the stock cleanup would have toggled. */
#define ACK_TIMEOUT_ASM(condition) \
    "push {r0-r3, lr}\n" \
    "movw r1, #0xffff\n" \
    "ldr r3, =0x403000e0\n" \
    "1: ldr r2, [r3]\n" \
    "lsls r2, r2, #7\n" \
    condition " 2f\n" \
    "subs r1, #1\n" \
    "bne 1b\n" \
    "ldr r2, [r3]\n" \
    "ubfx r1, r2, #24, #1\n" \
    "bfi r2, r1, #22, #1\n" \
    "str r2, [r3]\n" \
    "ldr r3, =0x200162b4\n" \
    "movs r2, #0\n" \
    "strb r2, [r3]\n" \
    "pop {r0-r3, lr}\n" \
    "movs r3, #0\n" \
    "bx lr\n" \
    "2: pop {r0-r3, lr}\n" \
    "ldr r3, =0x200162bc\n" \
    "ldrb r2, [r3]\n" \
    "rsb r2, r2, #1\n" \
    "sxtb r2, r2\n" \
    "strb r2, [r3]\n" \
    "ldr r3, =0x200162b4\n" \
    "bx lr\n"

__attribute__((used,naked)) int eoic_wait_ack_set(void) {
    __asm volatile(ACK_TIMEOUT_ASM("bmi"));
}
__attribute__((used,naked)) int eoic_wait_ack_clear(void) {
    __asm volatile(ACK_TIMEOUT_ASM("bpl"));
}
#endif

__attribute__((used)) int eoic_vendor(struct vendor *v) {
    const struct setup *s=v->setup;
    if (!custom(s)) return ((int (*)(struct vendor *))0x0020d999)(v);
    if (!format(s)) return 1;
    if (s->request==0xe0) {
        if (v->length != 0) return 1;
        v->payload=(const u8 *)&capabilities;
        v->length=sizeof(capabilities);
        return 0;
    }
    if (!ENABLE_EQ_TEST || !v->payload || v->length!=4) return 1;
    union { float f; u32 u; } gain;
    gain.u=(u32)v->payload[0] | (u32)v->payload[1]<<8 |
           (u32)v->payload[2]<<16 | (u32)v->payload[3]<<24;
    if (!finite(gain.f) || gain.f < -12 || gain.f > 0) return 1;
    const volatile u32 *state=(const volatile u32 *)0x200162c4;
    u32 rate=state[1];
    /* Both high-level EQ-enabled state and codec initialization must be live.
     * Reject concurrent coefficient updates. USB callback itself serializes EP0.
     */
#if GUARD_TRACE
    u8 enabled=*(const volatile u8 *)0x200162cd;
    TRACE_GUARD(0, enabled != 0);
    if (!enabled) return 1;
    u32 initialized=*(const volatile u32 *)0x200162b8;
    TRACE_GUARD(1, initialized != 0);
    if (!initialized) return 1;
    u8 busy=*(const volatile u8 *)0x200162b4;
    TRACE_GUARD(2, busy == 0);
    if (busy) return 1;
#else
    if (!*(const volatile u8 *)0x200162cd || !*(const volatile u32 *)0x200162b8 ||
        *(const volatile u8 *)0x200162b4) return 1;
#endif
    struct eq cfg;
    const u32 *stock=(const u32 *)0x20015bec;
    u32 *copy=(u32 *)&cfg;
    for (u32 i=0;i<sizeof(cfg)/4;++i) copy[i]=stock[i];
    cfg.left=cfg.right=gain.f;
#if GUARD_TRACE
    int valid=eoic_valid_eq(&cfg,rate);
    TRACE_GUARD(3, rate>=32000 && rate<=192000);
    TRACE_GUARD(4, valid);
    if (!valid) return 1;
#else
    if (!eoic_valid_eq(&cfg,rate)) return 1;
#endif
    /* Minimal test keeps the compiled stock band count and every band intact.
     * Dynamic topology changes and caller-supplied bands are not exposed.
     */
#if GUARD_TRACE
    TRACE_GUARD(5, cfg.count==2);
#endif
    if (cfg.count!=2) return 1;
    int result=((int (*)(u32,const struct eq *,u32))0x0020a939)(0,&cfg,2);
    return result != 0;
}
