/* Diagnostic-only wrapper around the hash-locked hardened EQ extension.
 * Private state occupies the reserved tail of the owned USB RX buffer.
 * No persistent operations, arbitrary addresses, or alternate EQ inputs. */
typedef unsigned char u8;
typedef unsigned short u16;
typedef unsigned int u32;
struct setup { u8 type, request; u16 value,index,length; };
struct frame { u8 state,pad[3]; const u8 *payload; u16 length,reserved; struct setup setup; };
struct vendor { const struct setup *setup; const u8 *payload; u16 length,pad; };
struct diag { u32 magic; u16 protocol,size; u32 sequence,events,outcome,result,timeouts,ready; };
_Static_assert(sizeof(struct diag)==32,"diagnostic wire size");
#define RX 0x20019804u
#define LIMIT 176u
#define STATE ((volatile struct diag *)(RX+LIMIT))
#define REPLY ((struct diag *)(RX+LIMIT+32))
#define MAGIC 0x47445145u
#define SEEN 1u
#define MATCHED 2u
#define ENTERED 4u
#define PAYLOAD 8u
#define CALLED 16u
#define SUCCESS 32u
#define ERROR 64u
#define TIMEOUT 128u
#define ARMED 256u
#define COMPLETE 512u
#ifndef GUARD_TRACE
#define GUARD_TRACE 0
#endif
#if GUARD_TRACE
static const u8 caps[12]={'E','O','I','C',1,0,8,0,3,0,0,0};
#else
static const u8 caps[12]={'E','O','I','C',1,0,8,0,1,0,0,0};
#endif

static int storage(void) {
    volatile u32 *p=(volatile u32 *)0x2001b160;
    if (p[0]!=RX || (p[1]!=240 && p[1]!=LIMIT)) return 0;
    p[1]=LIMIT;
    if (STATE->magic!=MAGIC) {
        volatile u32 *d=(volatile u32 *)STATE;
        for(u32 i=0;i<8;i++) d[i]=0;
        STATE->protocol=1; STATE->size=32; STATE->result=0xffffffffu;
        STATE->magic=MAGIC;
    }
    return 1;
}
static int matched(const struct setup *s,u8 type,u16 length) {
    return s->type==type && s->value==0x454f && s->index==0x4943 && s->length==length;
}
static u32 readiness(void) {
    u32 r=0,rate=*(volatile u32 *)0x200162c8;
    if (*(volatile u8 *)0x200162cd) r|=1;
    if (*(volatile u32 *)0x200162b8) r|=2;
    if (!*(volatile u8 *)0x200162b4) r|=4;
    if (rate>=32000 && rate<=192000) r|=8;
    if (*(const u32 *)0x20015bf4==2) r|=16;
    return r;
}
__attribute__((used)) int eoic_diag_setup(struct frame *f) {
    if (!storage()) return 0;
    const struct setup *s=&f->setup;
    if (s->request==0xe1) {
        STATE->sequence++; STATE->events=SEEN; STATE->outcome=1;
        STATE->result=0xffffffffu; STATE->timeouts=0; STATE->ready=readiness();
        if (!matched(s,0x40,4)) return 0;
        STATE->events|=MATCHED; STATE->outcome=0;
    }
    if (s->request==0xe2 && !matched(s,0xc0,32)) return 0;
    /* Fence every OUT DMA receive before the stock oversize receive path. */
    if (!(s->type&0x80) && s->length>LIMIT) return 0;
    return ((int (*)(struct frame *))0x0c04d001)(f);
}
__attribute__((used)) int eoic_diag_vendor(struct vendor *v) {
    const struct setup *s=v->setup;
    if (!storage()) return 1;
    if (s->request==0xe0 && matched(s,0xc0,12) && v->length==0) {
        v->payload=caps; v->length=12; return 0;
    }
    if (s->request==0xe2) {
        if (!matched(s,0xc0,32) || v->length) return 1;
        const volatile u32 *src=(const volatile u32 *)STATE;
        u32 *dst=(u32 *)REPLY;
        for(u32 i=0;i<8;i++) dst[i]=src[i];
        REPLY->ready=readiness(); v->payload=(const u8 *)REPLY; v->length=32;
        return 0;
    }
    if (s->request!=0xe1) return ((int (*)(struct vendor *))0x0c04d21d)(v);
    STATE->events|=ENTERED; STATE->outcome=6;
    if (!matched(s,0x40,4) || !v->payload || v->length!=4) return 1;
    u32 gain=(u32)v->payload[0]|(u32)v->payload[1]<<8|(u32)v->payload[2]<<16|(u32)v->payload[3]<<24;
    union {u32 u;float f;} g={gain};
    if ((gain&0x7f800000u)==0x7f800000u || g.f < -12 || g.f > 0) return 1;
    STATE->events|=PAYLOAD; STATE->outcome=2; STATE->ready=readiness();
    return ((int (*)(struct vendor *))0x0c04d21d)(v);
}
__attribute__((used)) int eoic_diag_eq_call(u32 type,const void *cfg,u32 filter) {
    STATE->events|=CALLED;
    int result=((int (*)(u32,const void *,u32))0x0020a939)(type,cfg,filter);
    STATE->result=(u32)result;
    if (!result) { STATE->events|=SUCCESS; STATE->outcome=3; }
    else { STATE->events|=ERROR; STATE->outcome=STATE->timeouts?5:4; }
    return result;
}
__attribute__((used)) int eoic_diag_data(struct frame *f) {
    int result=((int (*)(struct frame *))0x0020e5fd)(f);
    if (f->setup.request==0xe1 && matched(&f->setup,0x40,4) && result && f->state==6)
        STATE->events|=ARMED;
    return result;
}
__attribute__((used)) void eoic_diag_timeout(u32 mask) {
    if (STATE->magic==MAGIC && (STATE->events&CALLED) && !(STATE->events&(SUCCESS|ERROR))) {
        STATE->timeouts|=mask; STATE->events|=TIMEOUT;
    }
}
/* Call the exact unchanged original finite wait helpers, record only r3==0.
 * Preserve their register results and the original caller's stack alignment. */
#define WAIT_WRAPPER(low,mask) \
    "push {r4,lr}\n" \
    "movw r4, #" low "\n" \
    "movt r4, #0x0c04\n" \
    "blx r4\n" \
    "cmp r3,#0\n" \
    "bne 1f\n" \
    "push {r0-r3,r12,lr}\n" \
    "movs r0,#" mask "\n" \
    "bl eoic_diag_timeout\n" \
    "pop {r0-r3,r12,lr}\n" \
    "1: pop {r4,pc}\n"
__attribute__((used,naked)) void eoic_wait_ack_set(void) {
    __asm volatile(WAIT_WRAPPER("0xd19d","1"));
}
__attribute__((used,naked)) void eoic_wait_ack_clear(void) {
    __asm volatile(WAIT_WRAPPER("0xd1dd","2"));
}
__attribute__((used)) void eoic_diag_complete(struct frame *f) {
    if (STATE->magic==MAGIC && f->setup.request==0xe1 && matched(&f->setup,0x40,4)
        && (STATE->events&ARMED)) STATE->events|=COMPLETE;
}
/* Instrument the original state-6 IN-completion branch, then replay every
 * displaced instruction with the original register/flag effects. */
__attribute__((used,naked)) void eoic_diag_status_hook(void) {
    __asm volatile(
        "push {r0-r3,r12,lr}\n"
        "mov r0,r4\n"
        "bl eoic_diag_complete\n"
        "pop {r0-r3,r12,lr}\n"
        "movw r3,#0\n" "movt r3,#0x4018\n"
        "movw r1,#0xabf0\n" "movt r1,#0x2001\n"
        "movs r0,#0\n" "strb r0,[r4]\n"
        "ldr.w r2,[r3,#0x814]\n" "bx lr\n");
}
