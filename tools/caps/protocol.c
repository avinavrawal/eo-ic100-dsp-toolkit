/* Snapshot of original project transport; no legacy deployment CLI.
 * Strictly pinned BE60 version 1.0 / reported sector 36864. */

#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <inttypes.h>
#include <sys/stat.h>
#include <libusb-1.0/libusb.h>
#include <pthread.h>
#include <unistd.h>

#define VID_NORMAL 0x04e8
#define PID_NORMAL 0xa05e
#define VID_CDC    0xbe57
#define PID_CDC    0x0101

/*
 * Samsung's BES updater derives FLASH_BASE_ADDR from the high byte of the
 * image start address. For these images it is 0x3c000000, and READ_CMD as well
 * as boot-flag WRITE/ERASE commands use that mapped address space.
 */
#define FLASH_BASE       0x3c000000u
#define FLASH_SIZE       0x00080000u
#define FLAG_ADDR        (FLASH_BASE + 0x4000u)
#define BACKUP_FLAG_ADDR (FLASH_BASE + 0x5000u)
#define A_START          0x3c006000u
#define B_START          0x3c02e000u

static const uint8_t VALID_MAGIC[4]={0x1c,0xec,0x57,0xbe};
static uint8_t streambuf[16384];
static size_t streamlen=0;

static void die(const char *m,int rc){
    fprintf(stderr,"ERROR: %s (%d: %s)\n",m,rc,rc<0?libusb_error_name(rc):"unexpected");
    exit(2);
}
static uint32_t le32(const uint8_t*p){return (uint32_t)p[0]|((uint32_t)p[1]<<8)|((uint32_t)p[2]<<16)|((uint32_t)p[3]<<24);}
static void put32(uint8_t*p,uint32_t v){p[0]=v;p[1]=v>>8;p[2]=v>>16;p[3]=v>>24;}
static uint8_t chk(const uint8_t*p,size_t n){uint8_t s=0;for(size_t i=0;i<n;i++)s=(uint8_t)(s+p[i]);return (uint8_t)~s;}
static int frame_checksum_ok(const uint8_t*p,size_t n){uint8_t s=0;for(size_t i=0;i<n;i++)s=(uint8_t)(s+p[i]);return s==0xff;}
static uint32_t crc32_std(const uint8_t *p,size_t n){
    uint32_t c=0xffffffffu;
    for(size_t i=0;i<n;i++){
        c^=p[i];
        for(int j=0;j<8;j++)c=(c>>1)^(0xedb88320u & (0u-(c&1u)));
    }
    return c^0xffffffffu;
}
static uint8_t *readfile(const char*path,size_t*sz){
    FILE*f=fopen(path,"rb"); if(!f){perror(path);return NULL;}
    fseek(f,0,SEEK_END); long n=ftell(f); rewind(f);
    if(n<=0){fclose(f);return NULL;}
    uint8_t*b=malloc((size_t)n); if(!b){fclose(f);return NULL;}
    if(fread(b,1,(size_t)n,f)!=(size_t)n){fclose(f);free(b);return NULL;}
    fclose(f);*sz=(size_t)n;return b;
}
static int writefile(const char*path,const uint8_t*p,size_t n){
    FILE*f=fopen(path,"wb");if(!f)return -1;
    size_t w=fwrite(p,1,n,f);fclose(f);return w==n?0:-1;
}
static void loghex(const char*l,const uint8_t*p,size_t n){
    printf("%s",l);for(size_t i=0;i<n;i++)printf("%s%02x",i?" ":"",p[i]);printf("\n");fflush(stdout);
}
static int bulk_write(libusb_device_handle*h,const uint8_t*p,size_t n){
    size_t off=0;
    while(off<n){
        int want=(int)((n-off)>4096?4096:(n-off)),x=0;
        int rc=libusb_bulk_transfer(h,0x02,(unsigned char*)(p+off),want,&x,3000);
        if(rc||x!=want){fprintf(stderr,"bulk OUT failed rc=%d x=%d want=%d\n",rc,x,want);return -1;}
        off+=(size_t)x;
    }
    return 0;
}
static int sendmsg(libusb_device_handle*h,uint8_t cmd,uint8_t seq,const uint8_t*payload,uint8_t plen,const uint8_t*ext,size_t extlen){
#ifdef CAPS_READ_ONLY
    if(cmd!=0x01&&cmd!=0x03&&cmd!=0x50&&cmd!=0x53&&cmd!=0x54&&cmd!=0x55){
        fprintf(stderr,"READ_ONLY_GUARD: BES command %02x blocked before transport\n",cmd);return -90;
    }
#endif
    size_t hn=5u+plen;
    uint8_t*buf=malloc(hn+extlen); if(!buf)return -1;
    buf[0]=0xbe;buf[1]=cmd;buf[2]=seq;buf[3]=plen;
    if(plen)memcpy(buf+4,payload,plen);
    buf[4+plen]=chk(buf,4+plen);
    if(extlen)memcpy(buf+hn,ext,extlen);
    int r=bulk_write(h,buf,hn+extlen);
    free(buf);return r;
}
static int pull_frame(libusb_device_handle*h,uint8_t*out,size_t cap,int timeout_ms){
    int waited=0;
    while(waited<timeout_ms){
        /* discard bytes before BE */
        size_t start=0;while(start<streamlen&&streambuf[start]!=0xbe)start++;
        if(start){memmove(streambuf,streambuf+start,streamlen-start);streamlen-=start;}
        if(streamlen>=4){
            size_t total=5u+streambuf[3];
            if(total<=streamlen){
                if(total>cap)return -99;
                memcpy(out,streambuf,total);
                memmove(streambuf,streambuf+total,streamlen-total);streamlen-=total;
                return (int)total;
            }
        }
        uint8_t tmp[4096];int x=0;
        int slice=(timeout_ms-waited)>250?250:(timeout_ms-waited);
        int rc=libusb_bulk_transfer(h,0x82,tmp,sizeof(tmp),&x,slice);
        waited+=slice;
        if(rc==LIBUSB_ERROR_TIMEOUT)continue;
        if(rc){fprintf(stderr,"bulk IN rc=%d (%s)\n",rc,libusb_error_name(rc));return rc;}
        if(x>0){
            if(streamlen+(size_t)x>sizeof(streambuf))return -98;
            memcpy(streambuf+streamlen,tmp,(size_t)x);streamlen+=(size_t)x;
        }
    }
    return LIBUSB_ERROR_TIMEOUT;
}
static int expect(libusb_device_handle*h,uint8_t cmd,uint8_t*out,size_t cap,int timeout){
    for(int i=0;i<8;i++){
        int n=pull_frame(h,out,cap,timeout);
        if(n<0)return n;
        printf("RX ");for(int j=0;j<n;j++)printf("%02x",out[j]);printf("\n");
        if(!frame_checksum_ok(out,(size_t)n)){fprintf(stderr,"bad response checksum\n");return -20;}
        if(out[1]==cmd)return n;
        fprintf(stderr,"ignoring unrelated frame cmd=%02x while waiting for %02x\n",out[1],cmd);
    }
    return -21;
}
static int cdc_setup(libusb_device_handle*h){
    libusb_set_auto_detach_kernel_driver(h,1);
    int c0=libusb_claim_interface(h,0);
    int c1=libusb_claim_interface(h,1);
    printf("claim0=%d claim1=%d\n",c0,c1);
    if(c1<0)return c1;
    int rc=libusb_control_transfer(h,0x21,0x22,0,0,NULL,0,1000); if(rc<0)return rc;
    uint8_t line[7]={0x00,0x10,0x0e,0x00,0x00,0x00,0x08};
    rc=libusb_control_transfer(h,0x21,0x20,0,0,line,7,1000); if(rc!=7)return rc<0?rc:-30;
    rc=libusb_control_transfer(h,0x21,0x22,3,0,NULL,0,1000); if(rc<0)return rc;
    return c0==0?100:101; /* remember whether interface0 was claimed */
}
static void cdc_release(libusb_device_handle*h,int state){
    libusb_release_interface(h,1);if(state==100)libusb_release_interface(h,0);
}
static int bootstrap_programmer(libusb_device_handle*h,const char*progpath,uint32_t*burn_sector){
    size_t ps=0;uint8_t*pf=readfile(progpath,&ps);
    char programmer_hash[65];
    if(!pf || caps_sha(pf,ps,programmer_hash) || strcmp(programmer_hash,"97443fb54fd75f71abbb5e3231a7f9abae26babe55c07c6b7302df0594236845")){
        fprintf(stderr,"programmer SHA-256 differs before upload\n");free(pf);return -1;
    }
    if(!pf||ps<=1056){fprintf(stderr,"bad programmer asset\n");free(pf);return -1;}
    size_t dsz=ps-1056;uint8_t*data=pf+1052;uint32_t boot=le32(pf+ps-4);
    uint32_t crc=crc32_std(data,dsz);
    printf("programmer total=%zu data=%zu boot=%08x crc=%08x\n",ps,dsz,boot,crc);

    uint8_t f[512];int n=pull_frame(h,f,sizeof(f),1500);
    if(n!=8||f[0]!=0xbe||f[1]!=0x50||f[4]!=0||!frame_checksum_ok(f,n)){
        fprintf(stderr,"expected BE50 initial sync\n");free(pf);return -2;
    }
    uint8_t hp[1]={1};
    if(sendmsg(h,0x50,f[2],hp,1,NULL,0)){free(pf);return -3;}
    n=expect(h,0x50,f,sizeof(f),1500);
    if(n!=8||f[4]!=2){fprintf(stderr,"first handshake rejected\n");free(pf);return -4;}

    uint8_t info[12];put32(info,boot);put32(info+4,(uint32_t)dsz);put32(info+8,crc);
    if(sendmsg(h,0x53,1,info,12,NULL,0)){free(pf);return -5;}
    n=expect(h,0x53,f,sizeof(f),1500);
    if(n!=6||f[4]!=0){fprintf(stderr,"programmer info rejected status=%02x\n",n>4?f[4]:0xff);free(pf);return -6;}

    uint8_t meta[3]={0,0,0};
    printf("uploading programmer (%zu bytes)...\n",dsz);
    if(sendmsg(h,0x54,0xa2,meta,3,data,dsz)){free(pf);return -7;}
    n=expect(h,0x54,f,sizeof(f),5000);
    if(n!=6||f[4]!=0x20){fprintf(stderr,"programmer binary rejected status=%02x\n",n>4?f[4]:0xff);free(pf);return -8;}

    if(sendmsg(h,0x55,3,NULL,0,NULL,0)){free(pf);return -9;}

    /*
     * Real-device behavior: the RAM programmer can emit BE60 immediately after
     * PROGRAMMER_RUN, before (or instead of) the BE55 run-status frame.
     * Samsung's own parser treats BE60 independently and proceeds to boot-flag
     * reading when it arrives.  Do not discard BE60 while waiting for BE55.
     */
    int saw55=0, saw60=0;
    uint32_t ss=0;
    for(int tries=0; tries<12 && !saw60; tries++){
        n=pull_frame(h,f,sizeof(f),1000);
        if(n<0){
            if(n==LIBUSB_ERROR_TIMEOUT) continue;
            fprintf(stderr,"error waiting for programmer-run frames n=%d\n",n);
            free(pf);return -10;
        }
        printf("RX after PROGRAMMER_RUN ");
        for(int j=0;j<n;j++)printf("%02x",f[j]);
        printf("\n");
        if(!frame_checksum_ok(f,(size_t)n)){
            fprintf(stderr,"bad checksum after PROGRAMMER_RUN\n");free(pf);return -10;
        }
        if(f[1]==0x55){
            if(n==10 && f[4]==0){
                saw55=1;
                printf("RAM programmer run-status success; code return=%02x%02x%02x%02x\n",f[5],f[6],f[7],f[8]);
            }else{
                fprintf(stderr,"PROGRAMMER_RUN rejected/status frame invalid status=%02x len=%d\n",n>4?f[4]:0xff,n);
                free(pf);return -10;
            }
        }else if(f[1]==0x60){
            if(n!=11 || f[4]!=0 || f[5]!=1){
                fprintf(stderr,"invalid BE60 length=%d\n",n);free(pf);return -11;
            }
            ss=le32(f+6);
            saw60=1;
            printf("BE60 confirms RAM programmer is running; version=%u.%u reported_sector=%u\n",f[5],f[4],ss);
        }else{
            fprintf(stderr,"ignoring unrelated post-run frame cmd=%02x\n",f[1]);
        }
    }
    if(!saw60){
        fprintf(stderr,"no BE60 burn-programmer frame received\n");free(pf);return -11;
    }
    if(!saw55) printf("NOTE: BE60 arrived without a separate BE55 success frame; accepted per Samsung parser behavior.\n");
    if(ss!=36864){fprintf(stderr,"implausible sector size\n");free(pf);return -12;}
    *burn_sector=ss;
    free(pf);return 0;
}
/*
 * Exact large-read protocol recovered from Samsung's BEST3005 RAM programmer.
 *
 * Command 0x01 is the small READ_CMD used by Samsung for the 8-byte boot flag.
 * Command 0x03 is the separate BULK READ command.
 *
 * Command 0x03 request payload MUST be exactly 8 bytes:
 *     address LE32 + total_length LE32
 *
 * On success the programmer sends:
 *     BE 03 <seq> 01 00 <checksum>
 * followed immediately by exactly total_length raw bytes on bulk-IN 0x82.
 *
 * Programmer disassembly shows that it streams those bytes internally in
 * chunks of min(remaining, 0x1000).
 */
static int readmem(libusb_device_handle*h,uint32_t addr,uint8_t*out,uint8_t len){
    uint8_t p[5];put32(p,addr);p[4]=len;
    if(sendmsg(h,0x01,6,p,5,NULL,0))return -1;
    uint8_t f[512];int n=expect(h,0x01,f,sizeof(f),2000);
    if(n<0)return n;
    if(n==6 && f[4]!=0){
        fprintf(stderr,"READ_CMD error addr=%08x len=%u status=%02x\n",addr,len,f[4]);
        return 1000+f[4];
    }
    if(n!=(int)len+6 || f[4]!=0){
        fprintf(stderr,"READ_CMD malformed response addr=%08x n=%d len=%u status=%02x\n",
                addr,n,len,n>4?f[4]:0xff);
        return -2;
    }
    memcpy(out,f+5,len);return 0;
}

static uint8_t bulk_read_seq=0x30;

static int bulk_read_range(libusb_device_handle*h,uint32_t addr,uint8_t*out,size_t n){
    if(n==0)return 0;
    if(n>0xffffffffu){
        fprintf(stderr,"bulk read length too large\n");
        return -1;
    }
    if(streamlen!=0){
        fprintf(stderr,"SAFETY STOP: stale RX bytes before BULK READ: %zu\n",streamlen);
        return -2;
    }

    uint8_t payload[8];
    put32(payload,addr);
    put32(payload+4,(uint32_t)n);
    uint8_t seq=bulk_read_seq++;

    printf("BULK_READ request addr=0x%08x len=%zu seq=0x%02x\n",addr,n,seq);
    fflush(stdout);

    if(sendmsg(h,0x03,seq,payload,8,NULL,0)){
        fprintf(stderr,"BULK_READ request transfer failed\n");
        return -3;
    }

    uint8_t ack[64];
    int an=expect(h,0x03,ack,sizeof(ack),3000);
    if(an!=6 || ack[2]!=seq || ack[4]!=0){
        fprintf(stderr,
                "BULK_READ ACK invalid len=%d seq=%02x/%02x status=%02x\n",
                an,an>2?ack[2]:0xff,seq,an>4?ack[4]:0xff);
        return -4;
    }
    printf("BULK_READ ACK success.\n");

    /*
     * Exact programmer behavior recovered from code at 0x2f5e..0x2f9e:
     *   device_chunk = min(remaining, 0x1000)
     *   send(address, device_chunk)
     *
     * The send routine at 0x09cc fragments each device_chunk into <=64-byte
     * endpoint-2 IN packets. If device_chunk is an exact multiple of 64 it
     * explicitly queues a final zero-length packet. Since 0x1000 % 64 == 0,
     * every full 4096-byte programmer chunk is followed by one ZLP.
     *
     * Read one programmer chunk at a time and consume its expected ZLP before
     * accepting bytes from the next chunk. This also drains the final ZLP so a
     * later framed BES response cannot be confused by a stale zero packet.
     */
    size_t off=0;
    size_t next_report=65536;
    while(off<n){
        size_t dev_chunk=(n-off)>0x1000?0x1000:(n-off);
        size_t chunk_got=0;

        while(chunk_got<dev_chunk){
            size_t rem=dev_chunk-chunk_got;
            int want=(int)(rem>0x1000?0x1000:rem);
            int got=0;
            int rc=libusb_bulk_transfer(h,0x82,out+off+chunk_got,want,&got,5000);
            if(rc!=0){
                fprintf(stderr,
                        "BULK_READ data RX failed at total=%zu chunk=%zu/%zu rc=%d (%s)\n",
                        off+chunk_got,chunk_got,dev_chunk,rc,libusb_error_name(rc));
                return -5;
            }
            if(got==0){
                fprintf(stderr,
                        "Unexpected early ZLP inside data chunk at total=%zu chunk=%zu/%zu\n",
                        off+chunk_got,chunk_got,dev_chunk);
                return -6;
            }
            if(got>want){
                fprintf(stderr,"BULK_READ impossible RX length got=%d want=%d\n",got,want);
                return -7;
            }
            chunk_got+=(size_t)got;
        }

        off+=dev_chunk;

        if((dev_chunk & 0x3f)==0){
            unsigned char zbuf[64];
            int zgot=-1;
            int rc=libusb_bulk_transfer(h,0x82,zbuf,sizeof(zbuf),&zgot,2000);
            if(rc!=0){
                fprintf(stderr,
                        "Expected ZLP after %zu-byte programmer chunk but RX rc=%d (%s)\n",
                        dev_chunk,rc,libusb_error_name(rc));
                return -8;
            }
            if(zgot!=0){
                fprintf(stderr,
                        "Expected ZLP after %zu-byte programmer chunk but received %d data bytes\n",
                        dev_chunk,zgot);
                return -9;
            }
            printf("consumed expected ZLP after programmer chunk ending at %zu/%zu\n",off,n);
        }

        if(off>=next_report || off==n){
            printf("bulk-read %zu/%zu bytes\n",off,n);
            fflush(stdout);
            while(next_report<=off)next_report+=65536;
        }
    }

    printf("BULK_READ complete addr=0x%08x len=%zu\n",addr,n);
    return 0;
}

static int read_range(libusb_device_handle*h,uint32_t addr,uint8_t*out,size_t n){
    return bulk_read_range(h,addr,out,n);
}
static int read_flag(libusb_device_handle*h,uint8_t flag[8]){
    return readmem(h,FLAG_ADDR,flag,8);
}
static int flag_is(const uint8_t*f,char c){for(int i=0;i<8;i++)if(f[i]!=(uint8_t)c)return 0;return 1;}
static int load_candidate(const char*path,uint8_t**buf,size_t*sz,uint32_t*start){
    *buf=readfile(path,sz);if(!*buf||*sz<8)return -1;
    *start=le32(*buf+*sz-4);
    if(*start!=A_START&&*start!=B_START)return -2;
    if((*buf)[0]!=0xff||(*buf)[1]!=0xff||(*buf)[2]!=0xff||(*buf)[3]!=0xff)return -3;
    if((*start&0xff000000u)!=FLASH_BASE)return -4;
    return 0;
}

struct burn_rx_state {
    libusb_device_handle *h;
    pthread_mutex_t lock;
    volatile int stop;
    volatile int final_seen;
    volatile int fatal;
    unsigned final_index;
    unsigned ack_count;
    size_t sector_count;
    uint8_t accum[4096];
    size_t accum_len;
};

static void *burn_rx_thread(void *arg){
    struct burn_rx_state *st=(struct burn_rx_state*)arg;
    uint8_t tmp[4096];

    while(!st->stop){
        int got=0;
        int rc=libusb_bulk_transfer(st->h,0x82,tmp,sizeof(tmp),&got,500);

        if(rc==LIBUSB_ERROR_TIMEOUT) continue;

        if(rc!=0){
            pthread_mutex_lock(&st->lock);
            if(!st->stop){
                fprintf(stderr,"burn RX transport error rc=%d (%s)\n",
                        rc,libusb_error_name(rc));
                st->fatal=1;
            }
            pthread_mutex_unlock(&st->lock);
            break;
        }

        if(got<=0) continue;

        pthread_mutex_lock(&st->lock);

        if(st->accum_len+(size_t)got>sizeof(st->accum)){
            fprintf(stderr,"burn RX accumulator overflow\n");
            st->fatal=1;
            pthread_mutex_unlock(&st->lock);
            break;
        }

        memcpy(st->accum+st->accum_len,tmp,(size_t)got);
        st->accum_len+=(size_t)got;

        while(st->accum_len>=4){
            size_t skip=0;
            while(skip<st->accum_len && st->accum[skip]!=0xbe) skip++;

            if(skip){
                memmove(st->accum,st->accum+skip,st->accum_len-skip);
                st->accum_len-=skip;
            }

            if(st->accum_len<4) break;

            size_t fn=5u+st->accum[3];
            if(fn>st->accum_len) break;

            uint8_t frame[512];
            if(fn>sizeof(frame)){
                fprintf(stderr,"burn RX impossible frame size=%zu\n",fn);
                st->fatal=1;
                break;
            }

            memcpy(frame,st->accum,fn);
            memmove(st->accum,st->accum+fn,st->accum_len-fn);
            st->accum_len-=fn;

            printf("RX concurrent ");
            for(size_t j=0;j<fn;j++)printf("%02x",frame[j]);
            printf("\n");
            fflush(stdout);

            if(!frame_checksum_ok(frame,fn)){
                fprintf(stderr,"bad checksum in concurrent burn response\n");
                st->fatal=1;
                break;
            }

            if(frame[1]!=0x62){
                fprintf(stderr,"concurrent RX non-BE62 cmd=%02x ignored\n",frame[1]);
                continue;
            }

            if(fn!=8){
                fprintf(stderr,"unexpected BE62 length=%zu\n",fn);
                st->fatal=1;
                break;
            }

            if(frame[4]!=0x60){
                fprintf(stderr,"BURN_BIN device error status=%02x",frame[4]);
                if(frame[4]==0x63)fprintf(stderr," (no burn info)");
                else if(frame[4]==0x64)fprintf(stderr," (incorrect sector data length)");
                else if(frame[4]==0x65)fprintf(stderr," (sector data CRC error)");
                else if(frame[4]==0x66)fprintf(stderr," (sector sequence error)");
                else if(frame[4]==0x67)fprintf(stderr," (erase error)");
                else if(frame[4]==0x68)fprintf(stderr," (burn error)");
                fprintf(stderr,"\n");
                st->fatal=1;
                break;
            }

            unsigned ack=(unsigned)frame[5]|((unsigned)frame[6]<<8);
            st->ack_count++;
            printf("BURN_BIN ACK sector=%u (%u ACKs)\n",ack,st->ack_count);
            fflush(stdout);

            if(ack>=st->sector_count){
                fprintf(stderr,"invalid sector ACK=%u sectors=%zu\n",
                        ack,st->sector_count);
                st->fatal=1;
                break;
            }

            if(ack==st->final_index){
                st->final_seen=1;
                break;
            }
        }

        pthread_mutex_unlock(&st->lock);

        if(st->fatal||st->final_seen) break;
    }

    return NULL;
}

static int stage_image(libusb_device_handle*h,const uint8_t*img,size_t imgsz,uint32_t start,uint32_t reported_sector){
    size_t data_sz=imgsz-4;
    uint32_t ss=reported_sector>32768?32768:4096;
    uint8_t f[512];
    uint8_t bi[12];put32(bi,start);put32(bi+4,(uint32_t)data_sz);put32(bi+8,ss);
    printf("BURN_INFO start=%08x data=%zu sector=%u\n",start,data_sz,ss);
    if(sendmsg(h,0x61,3,bi,12,NULL,0))return -1;
    int n=expect(h,0x61,f,sizeof(f),3000);
    if(n!=6||f[4]!=0){fprintf(stderr,"burn info rejected status=%02x\n",n>4?f[4]:0xff);return -2;}

    size_t sectors=(data_sz+ss-1)/ss;

    /*
     * Samsung BesCdcDriver runs XwInputThread and XwOutputThread concurrently.
     * Keep a bulk-IN request pending while the main thread transmits sectors.
     */
    struct burn_rx_state br;
    memset(&br,0,sizeof(br));
    br.h=h;
    br.final_index=(unsigned)(sectors-1);
    br.sector_count=sectors;
    pthread_mutex_init(&br.lock,NULL);

    pthread_t rx_tid;
    if(pthread_create(&rx_tid,NULL,burn_rx_thread,&br)!=0){
        pthread_mutex_destroy(&br.lock);
        fprintf(stderr,"failed to create concurrent burn RX thread\n");
        return -3;
    }

    /* Give libusb time to submit the first IN transfer before sector 0. */
    usleep(100000);

    printf("Samsung concurrent burn: RX thread active; transmitting %zu sectors.\n",sectors);
    fflush(stdout);

    int tx_failed=0;
    for(size_t i=0;i<sectors;i++){
        pthread_mutex_lock(&br.lock);
        int rx_bad=br.fatal;
        pthread_mutex_unlock(&br.lock);
        if(rx_bad){
            tx_failed=1;
            fprintf(stderr,"stopping TX because RX reported a device/transport error\n");
            break;
        }

        size_t off=i*ss, len=(data_sz-off)>ss?ss:(data_sz-off);
        uint32_t crc=crc32_std(img+off,len);
        uint8_t m[11];
        put32(m,(uint32_t)len);
        put32(m+4,crc);
        m[8]=(uint8_t)i;
        m[9]=(uint8_t)(i>>8);
        m[10]=0;
        uint8_t seq=(uint8_t)(193u+i);

        printf("TX burn sector %zu/%zu len=%zu crc=%08x seq=%02x\n",
               i+1,sectors,len,crc,seq);
        fflush(stdout);

        if(sendmsg(h,0x62,seq,m,11,img+off,len)){
            fprintf(stderr,"sector %zu transport failed\n",i);
            tx_failed=1;
            break;
        }
    }

    if(tx_failed){
        pthread_mutex_lock(&br.lock);
        br.stop=1;
        pthread_mutex_unlock(&br.lock);
        pthread_join(rx_tid,NULL);
        pthread_mutex_destroy(&br.lock);
        return -4;
    }

    /* All sectors have been sent; let RX thread wait for the final ACK. */
    int waited_ms=0;
    while(waited_ms<120000){
        pthread_mutex_lock(&br.lock);
        int done=br.final_seen;
        int bad=br.fatal;
        unsigned ac=br.ack_count;
        pthread_mutex_unlock(&br.lock);

        if(done||bad) break;
        if((waited_ms%5000)==0){
            printf("waiting for final burn ACK... ACKs seen=%u elapsed=%ds\n",
                   ac,waited_ms/1000);
            fflush(stdout);
        }
        usleep(100000);
        waited_ms+=100;
    }

    pthread_mutex_lock(&br.lock);
    int final_seen=br.final_seen;
    int fatal=br.fatal;
    unsigned ack_count=br.ack_count;
    br.stop=1;
    pthread_mutex_unlock(&br.lock);

    pthread_join(rx_tid,NULL);
    pthread_mutex_destroy(&br.lock);

    if(fatal){
        fprintf(stderr,"burn failed after %u ACKs due to device/transport error\n",ack_count);
        return -5;
    }
    if(!final_seen){
        fprintf(stderr,"timed out waiting for final BURN_BIN ACK sector=%zu; ACKs seen=%u\n",
                sectors-1,ack_count);
        return -6;
    }

    printf("Final BURN_BIN ACK received for sector %zu; total ACKs=%u.\n",
           sectors-1,ack_count);
    fflush(stdout);

    uint8_t wm[9];wm[0]=0x22;put32(wm+1,start);memcpy(wm+5,VALID_MAGIC,4);
    printf("writing Samsung validity magic at %08x\n",start);
    if(sendmsg(h,0x65,18,wm,9,NULL,0))return -6;
    n=expect(h,0x65,f,sizeof(f),3000);
    if(n<6||f[4]!=0||f[2]!=18){fprintf(stderr,"validity magic write rejected\n");return -7;}
    return 0;
}
static int verify_candidate(libusb_device_handle*h,const uint8_t*img,size_t imgsz,uint32_t start){
    size_t n=imgsz-4;uint8_t*rb=malloc(n);if(!rb)return -1;
    printf("reading staged image back for verification (%zu bytes) from mapped address 0x%08x...\n",n,start);
    if(read_range(h,start,rb,n)){free(rb);return -2;}
    int ok=1;
    for(size_t i=0;i<n;i++){
        uint8_t exp=i<4?VALID_MAGIC[i]:img[i];
        if(rb[i]!=exp){fprintf(stderr,"verify mismatch at +0x%zx got=%02x expected=%02x\n",i,rb[i],exp);ok=0;break;}
    }
    free(rb);return ok?0:-3;
}
static int erase_flag_at(libusb_device_handle*h,uint32_t addr,uint8_t seq){
    uint8_t p[9],f[128];p[0]=0x21;put32(p+1,addr);p[5]=8;p[6]=p[7]=p[8]=0;
    if(sendmsg(h,0x65,seq,p,9,NULL,0))return -1;
    int n=expect(h,0x65,f,sizeof(f),4000);
    return (n>=6&&f[4]==0&&f[2]==seq)?0:-2;
}
static int write_flag_bytes_at(libusb_device_handle*h,uint32_t addr,uint8_t seq,const uint8_t flag[8]){
    uint8_t p[13],f[128];p[0]=0x22;put32(p+1,addr);memcpy(p+5,flag,8);
    if(sendmsg(h,0x65,seq,p,13,NULL,0))return -1;
    int n=expect(h,0x65,f,sizeof(f),4000);
    return (n>=6&&f[4]==0&&f[2]==seq)?0:-2;
}
