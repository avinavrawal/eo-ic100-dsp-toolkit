/* Scheduler telemetry plus passive codec transaction diagnostics.
 * This image never calls a codec setter or writes codec MMIO / busy state. */
typedef unsigned char u8;
typedef unsigned short u16;
typedef unsigned int u32;
struct setup { u8 type, request; u16 value,index,length; };
struct frame { u8 state,pad[3]; const u8 *payload; u16 length,reserved; struct setup setup; };
struct vendor { const struct setup *setup; const u8 *payload; u16 length,pad; };
struct telemetry {
    u32 magic; u16 protocol,size;
    volatile u32 app_loops,consumer_calls,event_signals,event_consumed;
    volatile u32 busy_zero_samples,busy_one_samples,queue_full;
    volatile u32 command_total_ticks,command_max_ticks,last_tick;
    volatile u8 queue_depth,queue_highwater,flags,reserved;
};
struct codec_diag {
    u32 magic; u16 protocol,size;
    volatile u32 transaction_entry,request_assert,ack_high,request_clear;
    volatile u32 ack_low,bank_toggle,busy_clear,error_exit;
    volatile u32 register_snapshot;
    volatile u8 selector,busy,request_bit,ack_bit,last_result;
    volatile u8 reserved[3];
};
struct progress_state {
    volatile u8 counts[6];
    volatile u8 last_checkpoint, branch_flags, copy_progress;
    volatile u16 cookie;
} __attribute__((packed));
struct progress_response {
    u32 magic; u16 protocol, size;
    u8 counts[6], last_checkpoint, branch_flags, copy_progress;
    u8 busy, selector, request_bit, ack_bit, reserved[3];
    u32 register_snapshot;
} __attribute__((packed));
_Static_assert(sizeof(struct setup)==8,"setup ABI");
_Static_assert(sizeof(struct frame)==20,"frame ABI");
_Static_assert(sizeof(struct vendor)==12,"vendor ABI");
_Static_assert(sizeof(struct telemetry)==52,"E3 ABI");
_Static_assert(sizeof(struct codec_diag)==52,"E4 ABI");
_Static_assert(sizeof(struct progress_state)==11,"progress RAM ABI");
_Static_assert(sizeof(struct progress_response)==28,"E5 ABI");

#define RX 0x20019804u
#define RX_LIMIT 128u
#define STATE ((volatile struct telemetry *)(RX+RX_LIMIT))
#define CODEC ((volatile struct codec_diag *)(RX+RX_LIMIT+sizeof(struct telemetry)))
#define PROGRESS ((volatile struct progress_state *)((volatile u8 *)CODEC+49u))
#define MAGIC 0x4d544345u /* ECTM */
#define CODEC_MAGIC 0x4b434145u /* EACK */
#define PROGRESS_MAGIC 0x47525045u /* EPRG */
#define PROGRESS_COOKIE 0xc0deu
#define QUEUE 0x200196acu
#define EVENT_WORD 0x20019a0cu
#define BUSY_BYTE 0x200162b4u
#define CODEC_REG 0x403000e0u
#define BANK_SELECTOR 0x200162bcu
#define CAPS_FLAGS 4u
#define EV_ENTRY 0u
#define EV_ASSERT 1u
#define EV_ACK_HIGH 2u
#define EV_CLEAR_REQ 3u
#define EV_ACK_LOW 4u
#define EV_BANK 5u
#define EV_BUSY_CLEAR 6u
#define EV_ERROR 7u
#define RESULT_NONE 0u
#define RESULT_ACTIVE 1u
#define RESULT_ACK_HIGH 2u
#define RESULT_REQUEST_CLEARED 3u
#define RESULT_ACK_LOW 4u
#define RESULT_SUCCESS 5u
#define RESULT_ERROR 6u
static const u8 caps[12]={'E','O','I','C',1,0,8,0,CAPS_FLAGS,0,0,0};
static const u8 empty_eq_diag[32]={
    'E','Q','D','G',1,0,32,0, 0,0,0,0, 0,0,0,0,
    0,0,0,0, 0xff,0xff,0xff,0xff, 0,0,0,0, 0,0,0,0
};

static u32 irq_save(void) {
    u32 old; __asm volatile("mrs %0, primask\n\tcpsid i" : "=r"(old) :: "memory"); return old;
}
static void irq_restore(u32 old) { if (!(old&1u)) __asm volatile("cpsie i" ::: "memory"); }
static void sat_inc(volatile u32 *p) { if (*p!=0xffffffffu) *p=*p+1u; }
static void sat_add(volatile u32 *p,u32 n) { if (0xffffffffu-*p<n) *p=0xffffffffu; else *p=*p+n; }
static void init_state_locked(void) {
    if (STATE->magic!=MAGIC) {
        volatile u32 *w=(volatile u32 *)STATE;
        for (u32 i=0;i<13;i++) w[i]=0;
        STATE->protocol=1; STATE->size=sizeof(*STATE);
        __asm volatile("dmb" ::: "memory"); STATE->magic=MAGIC;
    }
    if (CODEC->magic!=CODEC_MAGIC) {
        volatile u32 *w=(volatile u32 *)CODEC;
        for (u32 i=0;i<12;i++) w[i]=0;
        CODEC->protocol=1; CODEC->size=sizeof(*CODEC);
        __asm volatile("dmb" ::: "memory"); CODEC->magic=CODEC_MAGIC;
    }
    if (PROGRESS->cookie!=PROGRESS_COOKIE) {
        volatile u8 *p=(volatile u8 *)PROGRESS;
        for (u32 i=0;i<9u;i++) p[i]=0;
        PROGRESS->cookie=PROGRESS_COOKIE;
    }
}
static void init_state(void) { u32 old=irq_save(); init_state_locked(); irq_restore(old); }
static int storage(void) {
    volatile u32 *p=(volatile u32 *)0x2001b160u;
    if (p[0]!=RX || (p[1]!=240u && p[1]!=RX_LIMIT)) return 0;
    u32 old=irq_save(); init_state_locked(); p[1]=RX_LIMIT; irq_restore(old); return 1;
}
static int is_our_request(const struct setup *s) {
    return (s->type&0x60u)==0x40u && s->value==0x454fu && s->index==0x4943u &&
        (s->request==0xe0u || s->request==0xe1u || s->request==0xe2u ||
         s->request==0xe3u || s->request==0xe4u || s->request==0xe5u);
}
static int valid_read_request(const struct setup *s) {
    if (s->value!=0x454fu || s->index!=0x4943u || s->type!=0xc0u) return 0;
    if (s->request==0xe0u) return s->length==12u;
    if (s->request==0xe2u) return s->length==32u;
    if (s->request==0xe3u) return s->length==sizeof(*STATE);
    if (s->request==0xe4u) return s->length==sizeof(*CODEC);
    if (s->request==0xe5u) return s->length==sizeof(struct progress_response);
    return 0;
}
__attribute__((used)) int eoic_codec_setup(struct frame *f) {
    const struct setup *s=&f->setup;
    if (!storage()) return 0;
    if (s->request==0xe1u && is_our_request(s)) return 0;
    if (is_our_request(s) && !valid_read_request(s)) return 0;
    if (!(s->type&0x80u) && s->length>RX_LIMIT) return 0;
    return ((int (*)(struct frame *))0x0020dd11u)(f);
}
__attribute__((used)) int eoic_codec_vendor(struct vendor *v) {
    const struct setup *s=v->setup;
    if (!storage()) return 1;
    if (s->request==0xe0u && valid_read_request(s) && !v->length) { v->payload=caps; v->length=12; return 0; }
    if (s->request==0xe2u && valid_read_request(s) && !v->length) { v->payload=empty_eq_diag; v->length=32; return 0; }
    if (s->request==0xe3u && valid_read_request(s) && !v->length) {
        u32 old=irq_save(),busy=*(volatile u8 *)BUSY_BYTE,events=*(volatile u32 *)EVENT_WORD;
        u32 depth=*(volatile u8 *)(QUEUE+2u),high=*(volatile u8 *)(QUEUE+4u);
        STATE->queue_depth=(u8)depth; STATE->queue_highwater=(u8)high;
        STATE->flags=(u8)((busy?1u:0u)|((events&8u)?2u:0u)|(depth?4u:0u));
        __asm volatile("dmb" ::: "memory"); irq_restore(old);
        v->payload=(const u8 *)STATE; v->length=sizeof(*STATE); return 0;
    }
    if (s->request==0xe4u && valid_read_request(s) && !v->length) {
        u32 old=irq_save(); volatile u32 *dst=(volatile u32 *)RX;
        const volatile u32 *src=(const volatile u32 *)CODEC;
        for (u32 i=0;i<13u;i++) dst[i]=src[i];
        /* Progress state reuses E4's reserved tail internally. */
        dst[12]&=0x000000ffu;
        __asm volatile("dmb" ::: "memory"); irq_restore(old);
        v->payload=(const u8 *)RX; v->length=sizeof(*CODEC); return 0;
    }
    if (s->request==0xe5u && valid_read_request(s) && !v->length) {
        volatile struct progress_response *out=(volatile struct progress_response *)RX;
        u32 old=irq_save(),reg=*(volatile u32 *)CODEC_REG;
        out->magic=PROGRESS_MAGIC; out->protocol=1; out->size=sizeof(*out);
        for (u32 i=0;i<6u;i++) out->counts[i]=PROGRESS->counts[i];
        out->last_checkpoint=PROGRESS->last_checkpoint;
        out->branch_flags=PROGRESS->branch_flags;
        out->copy_progress=PROGRESS->copy_progress;
        out->busy=*(volatile u8 *)BUSY_BYTE;
        out->selector=*(volatile u8 *)BANK_SELECTOR;
        out->request_bit=(u8)((reg>>22)&1u); out->ack_bit=(u8)((reg>>24)&1u);
        out->reserved[0]=out->reserved[1]=out->reserved[2]=0;
        out->register_snapshot=reg;
        __asm volatile("dmb" ::: "memory"); irq_restore(old);
        v->payload=(const u8 *)RX; v->length=sizeof(*out); return 0;
    }
    if (s->request==0xe1u && is_our_request(s)) return 1;
    if (is_our_request(s)) return 1;
    return ((int (*)(struct vendor *))0x0020d999u)(v);
}
/* Event hook callbacks run in codec transaction context. Each update is one
 * saturating increment plus read-only snapshots inside a short IRQ mask. */
__attribute__((used)) void eoic_codec_record(u32 event) {
    u32 old=irq_save(); init_state_locked();
    volatile u32 *counter=(volatile u32 *)&CODEC->transaction_entry;
    if (event<8u) sat_inc(counter+event);
    u32 reg=*(volatile u32 *)CODEC_REG;
    CODEC->register_snapshot=reg; CODEC->request_bit=(u8)((reg>>22)&1u);
    CODEC->ack_bit=(u8)((reg>>24)&1u); CODEC->busy=*(volatile u8 *)BUSY_BYTE;
    CODEC->selector=*(volatile u8 *)BANK_SELECTOR;
    switch(event) {
    case EV_ENTRY: CODEC->last_result=RESULT_ACTIVE; break;
    case EV_ACK_HIGH: CODEC->last_result=RESULT_ACK_HIGH; break;
    case EV_CLEAR_REQ: CODEC->last_result=RESULT_REQUEST_CLEARED; break;
    case EV_ACK_LOW: CODEC->last_result=RESULT_ACK_LOW; break;
    case EV_BANK: CODEC->last_result=RESULT_SUCCESS; break;
    case EV_BUSY_CLEAR: CODEC->last_result=RESULT_SUCCESS; break;
    case EV_ERROR: CODEC->last_result=RESULT_ERROR; break;
    default: break;
    }
    __asm volatile("dmb" ::: "memory"); irq_restore(old);
}
/* Passive progress checkpoints; never writes codec MMIO or busy state. */
__attribute__((used)) void eoic_codec_progress(u32 event,u32 value) {
    u32 old=irq_save(); init_state_locked();
    if (event<6u) {
        if (PROGRESS->counts[event]!=0xffu) PROGRESS->counts[event]++;
        PROGRESS->last_checkpoint=(u8)event;
        if (event==0u) {
            if (value) PROGRESS->branch_flags|=1u; else PROGRESS->branch_flags&=(u8)~1u;
        } else if (event==1u) PROGRESS->branch_flags&=(u8)~2u;
        else if (event==2u) PROGRESS->branch_flags|=2u;
        else if (event==3u && PROGRESS->copy_progress!=0xffu) PROGRESS->copy_progress++;
        else if (event==5u) PROGRESS->branch_flags|=4u;
    }
    __asm volatile("dmb" ::: "memory"); irq_restore(old);
}
__attribute__((used)) int eoic_codec_queue_push(volatile u8 *q,u32 word) {
    u32 old=irq_save(),count=q[2],capacity=q[3];
    if (count>=capacity) { if ((u32)q==QUEUE && STATE->magic==MAGIC) sat_inc(&STATE->queue_full); irq_restore(old); return 1; }
    u32 tail=q[1]; volatile u32 *data=(volatile u32 *)(*(volatile u32 *)(q+8));
    data[tail]=word; if (++tail>=capacity) tail=0; q[1]=(u8)tail;
    q[2]=(u8)(++count); if (q[4]<count) q[4]=(u8)count; irq_restore(old); return 0;
}
__attribute__((used)) int eoic_codec_event_set(u32 bit) {
    if (bit>31u) return 1; u32 old=irq_save(); *(volatile u32 *)EVENT_WORD|=1u<<bit;
    if (bit==3u && STATE->magic==MAGIC) sat_inc(&STATE->event_signals); irq_restore(old); return 0;
}
__attribute__((used)) int eoic_codec_event_clear(u32 bit) {
    if (bit>31u) return 1; u32 old=irq_save(),mask=1u<<bit,word=*(volatile u32 *)EVENT_WORD;
    if (bit==3u && (word&mask) && STATE->magic==MAGIC) sat_inc(&STATE->event_consumed);
    *(volatile u32 *)EVENT_WORD=word&~mask; irq_restore(old); return 0;
}
static u32 read_timer(void) { return ((u32 (*)(void))0x00201789u)(); }
static void sample_loop(void) {
    u32 old=irq_save(),busy=*(volatile u8 *)BUSY_BYTE,events=*(volatile u32 *)EVENT_WORD;
    u32 depth=*(volatile u8 *)(QUEUE+2u),high=*(volatile u8 *)(QUEUE+4u);
    sat_inc(&STATE->app_loops); if (busy) sat_inc(&STATE->busy_one_samples); else sat_inc(&STATE->busy_zero_samples);
    STATE->queue_depth=(u8)depth; STATE->queue_highwater=(u8)high;
    STATE->flags=(u8)((busy?1u:0u)|((events&8u)?2u:0u)|(depth?4u:0u)); irq_restore(old);
}
__attribute__((used,noreturn)) void eoic_codec_app_loop(u32 value) {
    init_state();
    for (;;) {
        sample_loop(); u32 old=irq_save(); sat_inc(&STATE->consumer_calls); irq_restore(old);
        u32 start=read_timer(),result=((u32 (*)(u32))0x0020d1c9u)(value),elapsed=read_timer()-start;
        old=irq_save(); sat_add(&STATE->command_total_ticks,elapsed);
        if (elapsed>STATE->command_max_ticks) STATE->command_max_ticks=elapsed;
        STATE->last_tick=read_timer(); irq_restore(old);
        value=((u32 (*)(u32))0x00209a8du)(result);
    }
}
