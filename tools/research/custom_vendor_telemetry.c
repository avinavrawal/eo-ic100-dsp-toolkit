/* Read-only scheduler telemetry for the hash-locked Samsung 0.23 B image.
 * No DSP setter, codec-register writes, persistence, or USB write operation. */
typedef unsigned char u8;
typedef unsigned short u16;
typedef unsigned int u32;
struct setup { u8 type, request; u16 value,index,length; };
struct frame { u8 state,pad[3]; const u8 *payload; u16 length,reserved; struct setup setup; };
struct vendor { const struct setup *setup; const u8 *payload; u16 length,pad; };
struct telemetry {
    u32 magic;
    u16 protocol,size;
    volatile u32 app_loops,consumer_calls,event_signals,event_consumed;
    volatile u32 busy_zero_samples,busy_one_samples,queue_full;
    volatile u32 command_total_ticks,command_max_ticks,last_tick;
    volatile u8 queue_depth,queue_highwater,flags,reserved;
};
_Static_assert(sizeof(struct setup)==8,"setup ABI");
_Static_assert(sizeof(struct frame)==20,"frame ABI");
_Static_assert(sizeof(struct vendor)==12,"vendor ABI");
_Static_assert(sizeof(struct telemetry)==52,"E3 wire size");

#define RX 0x20019804u
#define RX_LIMIT 176u
#define STATE ((volatile struct telemetry *)(RX+RX_LIMIT))
#define MAGIC 0x4d544345u /* ECTM */
#define QUEUE 0x200196acu
#define EVENT_WORD 0x20019a0cu
#define BUSY_BYTE 0x200162b4u
#define CAPS_FLAGS 4u /* telemetry present; mutation capability absent */
static const u8 caps[12]={'E','O','I','C',1,0,8,0,CAPS_FLAGS,0,0,0};
/* No SET request has been accepted by this image. This keeps E2 readable and
 * explicitly reports the guard-trace-compatible empty state. */
static const u8 empty_eq_diag[32]={
    'E','Q','D','G',1,0,32,0, 0,0,0,0, 0,0,0,0,
    0,0,0,0, 0xff,0xff,0xff,0xff, 0,0,0,0, 0,0,0,0
};

static u32 irq_save(void) {
    u32 old;
    __asm volatile("mrs %0, primask\n\tcpsid i" : "=r"(old) :: "memory");
    return old;
}
static void irq_restore(u32 old) {
    if (!(old&1u)) __asm volatile("cpsie i" ::: "memory");
}
static void sat_inc(volatile u32 *p) { if (*p!=0xffffffffu) *p=*p+1u; }
static void sat_add(volatile u32 *p,u32 n) {
    if (0xffffffffu-*p<n) *p=0xffffffffu; else *p=*p+n;
}
static void init_state_locked(void) {
    if (STATE->magic!=MAGIC) {
        volatile u32 *w=(volatile u32 *)STATE;
        w[0]=0; w[1]=0; w[2]=0; w[3]=0; w[4]=0; w[5]=0; w[6]=0;
        w[7]=0; w[8]=0; w[9]=0; w[10]=0; w[11]=0; w[12]=0;
        STATE->protocol=1; STATE->size=sizeof(*STATE);
        __asm volatile("dmb" ::: "memory");
        STATE->magic=MAGIC;
    }
}
static void init_state(void) {
    u32 old=irq_save(); init_state_locked(); irq_restore(old);
}
static int storage(void) {
    volatile u32 *p=(volatile u32 *)0x2001b160u;
    if (p[0]!=RX || (p[1]!=240u && p[1]!=RX_LIMIT)) return 0;
    /* Reserve the already reviewed USB RX tail for fixed-size telemetry. */
    u32 old=irq_save(); init_state_locked(); p[1]=RX_LIMIT; irq_restore(old);
    return 1;
}
static int is_our_request(const struct setup *s) {
    return (s->type&0x60u)==0x40u && s->value==0x454fu && s->index==0x4943u &&
           (s->request==0xe0u || s->request==0xe1u ||
            s->request==0xe2u || s->request==0xe3u);
}
static int valid_read_request(const struct setup *s) {
    if (s->value!=0x454fu || s->index!=0x4943u) return 0;
    if (s->request==0xe0u) return s->type==0xc0u && s->length==12u;
    if (s->request==0xe2u) return s->type==0xc0u && s->length==32u;
    if (s->request==0xe3u) return s->type==0xc0u && s->length==sizeof(*STATE);
    return 0;
}

__attribute__((used)) int eoic_telemetry_setup(struct frame *f) {
    const struct setup *s=&f->setup;
    if (!storage()) return 0;
    /* E1 remains unavailable in this build, including a malformed matching
     * packet. The setup is rejected before the stock data-stage machinery. */
    if (s->request==0xe1u && is_our_request(s)) return 0;
    if (is_our_request(s) && !valid_read_request(s)) return 0;
    /* The telemetry occupies the reserved 64-byte tail used by the existing
     * diagnostic callback contract. Known stock command payloads are <=176 B. */
    if (!(s->type&0x80u) && s->length>RX_LIMIT) return 0;
    return ((int (*)(struct frame *))0x0020dd11u)(f);
}

__attribute__((used)) int eoic_telemetry_vendor(struct vendor *v) {
    const struct setup *s=v->setup;
    if (!storage()) return 1;
    if (s->request==0xe0u && valid_read_request(s) && !v->length) {
        v->payload=caps; v->length=12; return 0;
    }
    if (s->request==0xe2u && valid_read_request(s) && !v->length) {
        v->payload=empty_eq_diag; v->length=32; return 0;
    }
    if (s->request==0xe3u && valid_read_request(s) && !v->length) {
        u32 old=irq_save();
        u32 busy=*(volatile u8 *)BUSY_BYTE;
        u32 events=*(volatile u32 *)EVENT_WORD;
        u32 depth=*(volatile u8 *)(QUEUE+2u);
        u32 high=*(volatile u8 *)(QUEUE+4u);
        STATE->queue_depth=(u8)depth;
        STATE->queue_highwater=(u8)high;
        STATE->flags=(u8)((busy?1u:0u)|((events&8u)?2u:0u)|(depth?4u:0u));
        __asm volatile("dmb" ::: "memory");
        irq_restore(old);
        v->payload=(const u8 *)STATE; v->length=sizeof(*STATE); return 0;
    }
    if (s->request==0xe1u && is_our_request(s)) return 1;
    if (is_our_request(s)) return 1;
    return ((int (*)(struct vendor *))0x0020d999u)(v);
}

/* A bounded clone of the stock ring push at 0x20d54c, with exactly the same
 * fields, index wrap, return values and PRIMASK-preserving critical region. */
__attribute__((used)) int eoic_telemetry_queue_push(volatile u8 *q,u32 word) {
    u32 old=irq_save();
    u32 count=q[2],capacity=q[3];
    if (count>=capacity) {
        if ((u32)q==QUEUE && STATE->magic==MAGIC) sat_inc(&STATE->queue_full);
        irq_restore(old);
        return 1;
    }
    u32 tail=q[1];
    volatile u32 *data=(volatile u32 *)(*(volatile u32 *)(q+8));
    data[tail]=word;
    tail++;
    if (tail>=capacity) tail=0;
    q[1]=(u8)tail;
    count++;
    q[2]=(u8)count;
    if (q[4]<count) q[4]=(u8)count;
    irq_restore(old);
    return 0;
}

/* These wrappers preserve the stock event helper contract (bit 0..31, return
 * 0 on success, 1 out of range) and add bounded counters in the same masked
 * update. Event clear counts include all callers of the shared helper. */
__attribute__((used)) int eoic_telemetry_event_set(u32 bit) {
    if (bit>31u) return 1;
    u32 old=irq_save(),mask=1u<<bit;
    *(volatile u32 *)EVENT_WORD |= mask;
    if (bit==3u && STATE->magic==MAGIC) sat_inc(&STATE->event_signals);
    irq_restore(old);
    return 0;
}
__attribute__((used)) int eoic_telemetry_event_clear(u32 bit) {
    if (bit>31u) return 1;
    u32 old=irq_save(),mask=1u<<bit,word=*(volatile u32 *)EVENT_WORD;
    if (bit==3u && (word&mask) && STATE->magic==MAGIC) sat_inc(&STATE->event_consumed);
    *(volatile u32 *)EVENT_WORD=word&~mask;
    irq_restore(old);
    return 0;
}

static u32 read_timer(void) { return ((u32 (*)(void))0x00201789u)(); }
static void sample_loop(void) {
    u32 old=irq_save();
    u32 busy=*(volatile u8 *)BUSY_BYTE;
    u32 events=*(volatile u32 *)EVENT_WORD;
    u32 depth=*(volatile u8 *)(QUEUE+2u),high=*(volatile u8 *)(QUEUE+4u);
    sat_inc(&STATE->app_loops);
    if (busy) sat_inc(&STATE->busy_one_samples);
    else sat_inc(&STATE->busy_zero_samples);
    STATE->queue_depth=(u8)depth; STATE->queue_highwater=(u8)high;
    STATE->flags=(u8)((busy?1u:0u)|((events&8u)?2u:0u)|(depth?4u:0u));
    irq_restore(old);
}

/* Replaces only the loop body at 0x20aa82. It runs in the same app task and
 * calls the original consumer and event service in their original order. */
__attribute__((used,noreturn)) void eoic_telemetry_app_loop(u32 value) {
    init_state();
    for (;;) {
        sample_loop();
        u32 old=irq_save(); sat_inc(&STATE->consumer_calls); irq_restore(old);
        u32 start=read_timer();
        u32 result=((u32 (*)(u32))0x0020d1c9u)(value);
        u32 elapsed=read_timer()-start;
        old=irq_save();
        sat_add(&STATE->command_total_ticks,elapsed);
        if (elapsed>STATE->command_max_ticks) STATE->command_max_ticks=elapsed;
        STATE->last_tick=read_timer();
        irq_restore(old);
        value=((u32 (*)(u32))0x00209a8du)(result);
    }
}
