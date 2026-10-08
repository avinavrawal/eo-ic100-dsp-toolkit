/* Dedicated CAPS-only entry points; transport snapshot has no legacy CLI. */
#ifndef EOIC_CAPS_CORE_INCLUDED
#define EOIC_CAPS_CORE_INCLUDED
#include "sha256.h"
#ifndef CAPS_PROTOCOL_IMPORTED
#include "protocol.c"
#endif

#define A_BYTES 0x28000u
#define CAPS_BYTES 0x20004u
static uint8_t *authority,*caps_image;
static const char *asset_dir,*session_dir;
static const char *expected_image_hash;
static int setup_context(int fd,libusb_context **ctx,libusb_device_handle **h){
    int rc=libusb_set_option(NULL,LIBUSB_OPTION_NO_DEVICE_DISCOVERY);if(rc)return rc;
    rc=libusb_init(ctx);if(rc)return rc;
    return libusb_wrap_sys_device(*ctx,(intptr_t)fd,h);
}
static void stop(const char *why){fprintf(stderr,"CAPS_ABORT=%s\n",why);exit(70);}
static void need(int ok,const char *why){if(!ok)stop(why);}
static void pathjoin(char out[4096],const char *dir,const char *name){
    int n=snprintf(out,4096,"%s/%s",dir,name);need(n>0&&n<4096,"path too long");
}
static uint8_t *locked_file(const char *path,size_t size,const char *hash){
    size_t n=0;uint8_t *b=readfile(path,&n);char actual[65];
    need(b&&n==size,"asset length differs");need(!caps_sha(b,n,actual)&&!strcmp(actual,hash),"asset SHA-256 differs");return b;
}
static void assets(const char *dir,const char *image){
    char path[4096];asset_dir=dir;
    pathjoin(path,dir,"stock_b.bin");free(locked_file(path,0x1edc8,"2f418d3a324ec4217c32c4bf98d43c3cd07d59d81f82974f29320d399fa769f3"));
    pathjoin(path,dir,"flash-backup.bin");authority=locked_file(path,FLASH_SIZE,"6ee1089955817ac0deda01aab8eb7531f3bdd11dd1604fd8c143d6d1538eb0cd");
    pathjoin(path,dir,"programmer3001sp.bin");size_t n=0;uint8_t *p=readfile(path,&n);char hash[65];
    need(p&&n>1056&&!caps_sha(p,n,hash)&&!strcmp(hash,"97443fb54fd75f71abbb5e3231a7f9abae26babe55c07c6b7302df0594236845"),"programmer hash differs");free(p);
#ifdef EQ_TUNER
    need(expected_image_hash&&strlen(expected_image_hash)==64,"EQ image hash argument missing");
    caps_image=locked_file(image,CAPS_BYTES,expected_image_hash);
#else
    caps_image=locked_file(image,CAPS_BYTES,"afa5bb0570950030c7e36c3219fd93e0efc65c90f5355e02d4a3a091cb6bf356");
#endif
    need(le32(caps_image+CAPS_BYTES-4)==B_START&&le32(caps_image)==0xffffffff,"patched image header/footer differs");
    need(!memcmp(authority+0x6000,VALID_MAGIC,4)&&le32(authority+0x600c)==0x3c026394,"original A header differs");
    puts("CAPS_LOCAL_HASHES=VERIFIED");
}
static void save(const char *name,const uint8_t *b,size_t n){
    char path[4096];pathjoin(path,session_dir,name);
    FILE *f=fopen(path,"wbx");need(f!=NULL,"refusing existing or unwritable evidence file");
    int good=fwrite(b,1,n,f)==n;if(fflush(f)||fsync(fileno(f)))good=0;if(fclose(f))good=0;need(good,"evidence save failed");
}
static int a_flag(const uint8_t *b){return flag_is(b,'A')||!memcmp(b,authority+0x4000,8);}
static int known_flag(const uint8_t *b){return a_flag(b)||flag_is(b,'B');}
static void verify_a(libusb_device_handle *h,const char *name){
    uint8_t *b=malloc(A_BYTES);need(b!=NULL,"allocation");
    need(!read_range(h,A_START,b,A_BYTES),"full A read failed");
    need(!memcmp(b,VALID_MAGIC,4)&&le32(b+12)==0x3c026394,"A validity/header differs");
    save(name,b,A_BYTES);need(!memcmp(b,authority+0x6000,A_BYTES),"complete A differs from preserved original backup");free(b);
    puts("CAPS_A_FULL_READBACK=VERIFIED bytes=163840 address=0x3c006000");
}
static void verify_b(libusb_device_handle *h,const char *name){
    uint8_t *b=malloc(0x20000);need(b!=NULL,"allocation");need(!read_range(h,B_START,b,0x20000),"full B read failed");save(name,b,0x20000);
    need(!memcmp(b,VALID_MAGIC,4)&&!memcmp(b+4,caps_image+4,0x20000-4),"complete marked B readback differs");free(b);
    puts("CAPS_B_FULL_READBACK=VERIFIED bytes=131072 address=0x3c02e000");
}
static void flags(libusb_device_handle *h,uint8_t out[8192],const char *name){
    need(!read_range(h,FLAG_ADDR,out,4096)&&!read_range(h,BACKUP_FLAG_ADDR,out+4096,4096),"full flags read failed");
    need(known_flag(out),"unknown boot flag");
    /* Accept the complete recorded factory sector, or known canonical flag
     * sector shape after the previously tested Samsung-style erase/write. */
    if(memcmp(out,authority+0x4000,4096)){
      need(flag_is(out,'A')||flag_is(out,'B'),"active flag sector is not original/canonical");
      for(size_t i=8;i<4096;i++)need(out[i]==0xff,"active flag sector has unexpected extra data");
    }
    for(size_t i=4104;i<8192;i++)need(out[i]==0xff,"backup flag sector has unexpected extra data");
    int ff=1;for(unsigned i=0;i<8;i++)if(out[4096+i]!=0xff)ff=0;
    need(ff||known_flag(out+4096),"unknown backup flag");save(name,out,8192);
}
static void normal_query(libusb_device_handle *h,int expected){
    uint8_t b[32];const char *q="QUERY_SW_VER";int n;
    need(libusb_control_transfer(h,0x40,6,0,0,(unsigned char*)q,12,2000)==12,"QUERY_SW_VER OUT failed");
    n=libusb_control_transfer(h,0xc0,12,0,0,b,14,1500);need(n==14,"firmware reply length differs");
    need(expected=='A'?!memcmp(b,"0.04_051101_aa",14):!memcmp(b,"0.23_051101_ab",14),"firmware version/slot differs");
    printf("FW=%.*s\n",14,b);
    q="CHECK";need(libusb_control_transfer(h,0x40,6,0,0,(unsigned char*)q,5,2000)==5,"CHECK OUT failed");
    n=libusb_control_transfer(h,0xc0,12,0,0,b,3,1500);need(n==3&&!memcmp(b,"1.1",3),"CHECK differs");puts("CHECK=1.1");
}
static void normal_query_any(libusb_device_handle *h){
    uint8_t b[32];const char *q="QUERY_SW_VER";
    need(libusb_control_transfer(h,0x40,6,0,0,(unsigned char*)q,12,2000)==12,"QUERY_SW_VER OUT failed");
    int n=libusb_control_transfer(h,0xc0,12,0,0,b,14,1500);need(n==14,"firmware reply length differs");
    printf("FW=%.*s\n",14,b);
    if(!memcmp(b,"0.04_051101_aa",14))puts("ACTIVE_SLOT=A (inferred from Samsung version suffix)");
    else if(!memcmp(b,"0.23_051101_ab",14))puts("ACTIVE_SLOT=B (inferred from Samsung version suffix)");
    else puts("ACTIVE_SLOT=UNKNOWN (unrecognized version suffix)");
    q="CHECK";need(libusb_control_transfer(h,0x40,6,0,0,(unsigned char*)q,5,2000)==5,"CHECK OUT failed");
    n=libusb_control_transfer(h,0xc0,12,0,0,b,3,1500);need(n==3&&!memcmp(b,"1.1",3),"CHECK differs");printf("CHECK=%.*s\n",n,b);
}
static void enter(libusb_device_handle *h,int expected){
    normal_query(h,expected);uint8_t b[1];const char *q="FW_UPDATE";
    need(libusb_control_transfer(h,0x40,6,0,0,(unsigned char*)q,9,4000)==9,"FW_UPDATE failed");
    need(libusb_control_transfer(h,0xc0,12,0,0,b,1,2000)==1&&b[0]=='1',"FW_UPDATE ACK differs");
    q="SYS_REBOOT";need(libusb_control_transfer(h,0x40,6,0,0,(unsigned char*)q,10,3000)==10,"OTA SYS_REBOOT failed");
    /* Established updater completion read; disconnect is expected here. */
    (void)libusb_control_transfer(h,0xc0,12,0,0,b,1,1000);
    puts("CAPS_OTA_ENTRY_SENT=YES");
}
static void bootstrap(libusb_device_handle *h){
    char path[4096];pathjoin(path,asset_dir,"programmer3001sp.bin");uint32_t sector=0;
    need(!bootstrap_programmer(h,path,&sector)&&sector==36864,"programmer bootstrap/version/sector differs");
}
static void switch_flag(libusb_device_handle *h,const uint8_t before[8192],char target,int backup){
    if(backup){
      need(!erase_flag_at(h,BACKUP_FLAG_ADDR,16)&&!write_flag_bytes_at(h,BACKUP_FLAG_ADDR,17,before),"backup flag write failed");
      uint8_t b[4096];need(!read_range(h,BACKUP_FLAG_ADDR,b,4096),"backup flag readback failed");
      need(!memcmp(b,before,8)&&!memcmp(b+8,before+4104,4088),"backup flag/sector readback differs");save("backup-flag-after.bin",b,4096);
    }
    uint8_t t[8];memset(t,target,8);
    need(!erase_flag_at(h,FLAG_ADDR,19)&&!write_flag_bytes_at(h,FLAG_ADDR,20,t),"active flag write failed");
    uint8_t after[8192];flags(h,after,"flags-after.bin");need(flag_is(after,target),"target flag differs");
    /* Established flag erase removes factory sector contents. The complete
     * before-sector is saved locally; canonical after-sector must be FF. */
    for(size_t i=8;i<4096;i++)need(after[i]==0xff,"canonical active flag sector differs");
    need(!memcmp(after+4096,backup?before:before+4096,8)&&!memcmp(after+4104,before+4104,4088),"backup flag changed unexpectedly");
    printf("CAPS_BOOT_SELECTION=%c VERIFIED\n",target);puts("CAPS_SOFTWARE_REBOOT_SENT=NO");
}
int main(int argc,char **argv){
    setvbuf(stdout,NULL,_IONBF,0);need(argc==6,"arguments: MODE PRIVATE CAPS PHASE_DIRECTORY FD");
    const char *mode=argv[1];session_dir=argv[4];assets(argv[2],argv[3]);
    int fd=-1;char extra;need(sscanf(argv[5],"%d%c",&fd,&extra)==1&&fd>=0,"invalid USB fd");
    libusb_context *ctx=NULL;libusb_device_handle *h=NULL;need(!setup_context(fd,&ctx,&h),"USB fd wrap failed");
    struct libusb_device_descriptor d;need(!libusb_get_device_descriptor(libusb_get_device(h),&d),"USB descriptor failed");
    printf("VID:PID=%04x:%04x\n",d.idVendor,d.idProduct);
    if(!strcmp(mode,"identify"))goto done;
    if(!strcmp(mode,"query-A")||!strcmp(mode,"enter-A")||!strcmp(mode,"enter-B")||!strcmp(mode,"probe")){
      need(d.idVendor==VID_NORMAL&&d.idProduct==PID_NORMAL,"expected 04e8:a05e");
      if(!strcmp(mode,"probe")){uint8_t b[12];const uint8_t expected[12]={'E','O','I','C',1,0,8,0,0,0,0,0};need(libusb_control_transfer(h,0xc0,0xe0,0x454f,0x4943,b,12,1000)==12&&!memcmp(b,expected,12),"CAPS reply differs or transfer failed");loghex("CAPS_RESPONSE=",b,12);}
      else if(!strcmp(mode,"query-A"))normal_query(h,'A');else enter(h,!strcmp(mode,"enter-A")?'A':'B');
      goto done;
    }
    need(!strcmp(mode,"stage-bootstrap")||!strcmp(mode,"activate-running")||!strcmp(mode,"recover-running")||!strcmp(mode,"recover-bootstrap")||!strcmp(mode,"recover-bootstrap-A")||!strcmp(mode,"recover-bootstrap-B"),"unknown mode");
    need(d.idVendor==VID_CDC&&d.idProduct==PID_CDC,"expected be57:0101");
    int cs=cdc_setup(h);need(cs>=0,"CDC setup failed");
    if(strstr(mode,"bootstrap"))bootstrap(h);
    verify_a(h,"a-before.bin");uint8_t before[8192];flags(h,before,"flags-before.bin");
    if(!strcmp(mode,"recover-bootstrap-A"))need(a_flag(before),"queried A but boot selection differs");
    if(!strcmp(mode,"recover-bootstrap-B"))need(flag_is(before,'B'),"queried B but boot selection differs");
    if(!strcmp(mode,"stage-bootstrap")){
      need(a_flag(before),"staging requires A selected");
      puts("CAPS_TARGET=B ONLY address=0x3c02e000 length=131072");
      need(!stage_image(h,caps_image,CAPS_BYTES,B_START,36864),"B stage failed; do not activate");
      verify_b(h,"b-staged.bin");verify_a(h,"a-after.bin");uint8_t after[8192];flags(h,after,"flags-after.bin");
      need(!memcmp(before,after,8192),"boot flags changed during stage");puts("CAPS_BOOT_FLAGS_UNCHANGED=YES");
    }else if(!strcmp(mode,"activate-running")){
      need(a_flag(before),"activation requires A selected");verify_b(h,"b-before.bin");
      char path[4096];pathjoin(path,session_dir,"../stage/flags-before.bin");size_t n=0;uint8_t *prior=readfile(path,&n);
      need(prior&&n==8192&&!memcmp(prior,before,8192),"flags differ from stage session");free(prior);
      switch_flag(h,before,'B',1);
    }else{
      /* Recovery writes only the active boot flag, never either image or backup flag. */
      if(a_flag(before)){
        uint8_t after[8192];flags(h,after,"flags-after.bin");
        need(!memcmp(before,after,8192)&&a_flag(after),"already-A flags changed on verification");
        puts("CAPS_ALREADY_A=YES no write");puts("CAPS_SOFTWARE_REBOOT_SENT=NO");
      }else switch_flag(h,before,'A',0);
    }
    cdc_release(h,cs);
done:
    printf("CAPS_PHASE_OK=%s\n",mode);libusb_close(h);libusb_exit(ctx);free(authority);free(caps_image);return 0;
}
#endif
