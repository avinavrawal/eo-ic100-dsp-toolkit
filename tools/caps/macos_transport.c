/* Native libusb opener; default validation binary blocks all flash commands. */
#define main caps_termux_entry_not_used
#include "caps_transport.c"
#undef main
#include <time.h>

static void native_open(int programmer,libusb_context **ctx,libusb_device_handle **h){
    need(!libusb_init(ctx),"native libusb init failed");
    libusb_device **list=NULL;ssize_t n=libusb_get_device_list(*ctx,&list);need(n>=0,"native enumeration failed");
    libusb_device *match=NULL;unsigned count=0;
    for(ssize_t i=0;i<n;i++){
      struct libusb_device_descriptor d;need(!libusb_get_device_descriptor(list[i],&d),"descriptor read failed");
      if(d.idVendor==(programmer?VID_CDC:VID_NORMAL)&&d.idProduct==(programmer?PID_CDC:PID_NORMAL)){match=list[i];count++;}
    }
    need(count==1,"exactly one expected native USB identity required");
    int rc=libusb_open(match,h);libusb_free_device_list(list,1);need(!rc,"native libusb open failed");
    struct libusb_device_descriptor d;need(!libusb_get_device_descriptor(libusb_get_device(*h),&d),"opened descriptor failed");
    need(d.idVendor==(programmer?VID_CDC:VID_NORMAL)&&d.idProduct==(programmer?PID_CDC:PID_NORMAL),"opened identity changed");
    printf("VID:PID=%04x:%04x\n",d.idVendor,d.idProduct);
}
/* Activation-only selector: enumerate for up to ten seconds, require three
 * consecutive snapshots containing exactly one USB device and that device
 * must be the known programmer. It never claims an interface or sends USB
 * transfers. Unknown/normal identities and duplicate programmers fail closed. */
static void stable_programmer(libusb_context *ctx,int open_device,libusb_device_handle **h){
    struct timespec start,now,pause={0,100000000};
    need(clock_gettime(CLOCK_MONOTONIC,&start)==0,"monotonic clock unavailable");
    unsigned poll=0,streak=0;
    for(;;){
      need(clock_gettime(CLOCK_MONOTONIC,&now)==0,"monotonic clock failed");
      long elapsed=(now.tv_sec-start.tv_sec)*1000L+(now.tv_nsec-start.tv_nsec)/1000000L;
      if(elapsed>=10000)break;
      libusb_device **list=NULL;ssize_t n=libusb_get_device_list(ctx,&list);
      need(n>=0,"stable USB enumeration failed");
      unsigned expected=0,unexpected=0;libusb_device *match=NULL;poll++;
      printf("ENUM_POLL=%u elapsed_ms=%ld device_count=%ld\n",poll,elapsed,(long)n);
      for(ssize_t i=0;i<n;i++){
        struct libusb_device_descriptor d;
        need(!libusb_get_device_descriptor(list[i],&d),"USB descriptor read failed during stabilization");
        unsigned bus=libusb_get_bus_number(list[i]),address=libusb_get_device_address(list[i]);
        printf("ENUM_USB=%04x:%04x bus=%u address=%u\n",d.idVendor,d.idProduct,bus,address);
        if(d.idVendor==VID_CDC&&d.idProduct==PID_CDC){expected++;match=list[i];}
        else unexpected++;
      }
      printf("ENUM_POLL_RESULT=%u expected_programmers=%u unexpected_devices=%u\n",poll,expected,unexpected);
      if(expected>1){libusb_free_device_list(list,1);stop("multiple be57:0101 programmer devices observed");}
      if(unexpected){libusb_free_device_list(list,1);stop("unexpected USB identity during activation preflight");}
      if(expected==1&&n==1)streak++;else streak=0;
      if(streak>=3){
        printf("ENUM_STABLE=be57:0101 consecutive_polls=%u elapsed_ms=%ld\n",streak,elapsed);
        if(open_device){
          int rc=libusb_open(match,h);libusb_free_device_list(list,1);
          need(!rc,"stable programmer open failed");
          struct libusb_device_descriptor d;
          need(!libusb_get_device_descriptor(libusb_get_device(*h),&d),"opened programmer descriptor failed");
          need(d.idVendor==VID_CDC&&d.idProduct==PID_CDC,"opened programmer identity changed after stabilization");
          printf("VID:PID=%04x:%04x\n",d.idVendor,d.idProduct);
        }else libusb_free_device_list(list,1);
        return;
      }
      libusb_free_device_list(list,1);
      (void)nanosleep(&pause,NULL);
    }
    stop("be57:0101 did not remain the sole USB identity for three consecutive polls within 10 seconds");
}
static void native_open_stable_programmer(libusb_context **ctx,libusb_device_handle **h){
    need(!libusb_init(ctx),"native libusb init failed");
    stable_programmer(*ctx,1,h);
}
static void descriptors(libusb_device_handle *h,int programmer){
    struct libusb_config_descriptor *c=NULL;need(!libusb_get_active_config_descriptor(libusb_get_device(h),&c),"active configuration descriptor failed");
    printf("CONFIG interfaces=%u total=%u value=%u\n",c->bNumInterfaces,c->wTotalLength,c->bConfigurationValue);
    int in=0,out=0,hid=0,audio=0;
    for(unsigned i=0;i<c->bNumInterfaces;i++)for(int j=0;j<c->interface[i].num_altsetting;j++){
      const struct libusb_interface_descriptor *a=&c->interface[i].altsetting[j];
      printf("INTERFACE=%u alt=%u class=%02x subclass=%02x protocol=%02x\n",a->bInterfaceNumber,a->bAlternateSetting,a->bInterfaceClass,a->bInterfaceSubClass,a->bInterfaceProtocol);
      if(!programmer&&a->bInterfaceClass==1)audio=1;
      for(unsigned e=0;e<a->bNumEndpoints;e++){
        const struct libusb_endpoint_descriptor *p=&a->endpoint[e];printf("ENDPOINT=%02x attributes=%02x packet=%u interval=%u\n",p->bEndpointAddress,p->bmAttributes,p->wMaxPacketSize,p->bInterval);
        if((p->bmAttributes&3)==2&&p->bEndpointAddress==0x82)in=1;
        if((p->bmAttributes&3)==2&&p->bEndpointAddress==0x02)out=1;
      }
      if(!programmer&&a->bInterfaceClass==3&&a->bAlternateSetting==0){
        need(a->bInterfaceNumber==3,"HID interface differs");uint8_t b[47];
        int n=libusb_control_transfer(h,0x81,6,0x2200,3,b,sizeof(b),2000);need(n==47,"HID report length differs");loghex("HID_REPORT=",b,n);hid++;
      }
    }
    libusb_free_config_descriptor(c);
    if(programmer)need(in&&out,"expected CDC bulk endpoints 02/82 absent");
    else {need(hid==1,"expected normal HID missing");need(audio,"expected USB audio interface missing");puts("AUDIO_INTERFACE=YES");puts("HID_INTERFACE=YES");}
}
static void native_read_all(libusb_device_handle *h,int launch){
    descriptors(h,1);int cs=cdc_setup(h);need(cs>=0,"native CDC setup failed");
    if(launch)bootstrap(h);
    uint8_t *b=malloc(FLASH_SIZE);need(b!=NULL,"allocation");
    need(!read_range(h,FLASH_BASE,b,FLASH_SIZE),"complete native flash read failed");
    save("flash-current.bin",b,FLASH_SIZE);char hash[65];need(!caps_sha(b,FLASH_SIZE,hash),"hash failed");
    printf("FLASH_CURRENT_SHA256=%s\n",hash);
    printf("FLASH_EXACT_BACKUP_MATCH=%s\n",memcmp(b,authority,FLASH_SIZE)?"NO":"YES");
    need(!memcmp(b+0x6000,authority+0x6000,A_BYTES),"original A changed");
    need(!memcmp(b+0x6000,VALID_MAGIC,4)&&le32(b+0x600c)==0x3c026394,"original A header differs");
    need(!memcmp(b+0x2e000,VALID_MAGIC,4),"installed B marker differs");
    loghex("CURRENT_ACTIVE_FLAG=",b+0x4000,8);loghex("CURRENT_BACKUP_FLAG=",b+0x5000,8);
    free(b);puts("NATIVE_FULL_FLASH_READ=VERIFIED 524288 bytes; no persistent write");cdc_release(h,cs);
}
static uint8_t *validated_baseline(void){
    char path[4096];pathjoin(path,session_dir,"../baseline.bin");
    return locked_file(path,FLASH_SIZE,"077317b51d1df4b358603fafc690a92e8bc5a17f116c24d3edf9223c4ae150e2");
}
static uint8_t *whole_flash(libusb_device_handle *h,const char *name){
    uint8_t *b=malloc(FLASH_SIZE);need(b!=NULL,"allocation");need(!read_range(h,FLASH_BASE,b,FLASH_SIZE),"full pre/post-write flash read failed");save(name,b,FLASH_SIZE);return b;
}
static libusb_device_handle *capture_programmer(libusb_context *ctx){
    for(unsigned attempt=0;attempt<400;attempt++){
      struct timeval wait={0,25000};need(!libusb_handle_events_timeout(ctx,&wait),"hotplug event handling failed");
      libusb_device **list=NULL;ssize_t n=libusb_get_device_list(ctx,&list);need(n>=0,"capture enumeration failed");
      libusb_device *found=NULL;unsigned count=0;
      for(ssize_t i=0;i<n;i++){struct libusb_device_descriptor d;need(!libusb_get_device_descriptor(list[i],&d),"capture descriptor failed");if(d.idVendor==VID_CDC&&d.idProduct==PID_CDC){found=list[i];count++;}}
      need(count<=1,"ambiguous programmer capture");
      if(found){libusb_device_handle *h=NULL;int rc=libusb_open(found,&h);libusb_free_device_list(list,1);need(!rc,"captured programmer open failed");printf("PROGRAMMER_CAPTURE_MS=%u\n",(attempt+1)*25);return h;}
      libusb_free_device_list(list,1);
    }
    stop("known OTA transition did not expose be57:0101 during immediate 10-second capture");return NULL;
}
#ifndef MACOS_ENTRY
#define MACOS_ENTRY main
#endif
int MACOS_ENTRY(int argc,char **argv){
    setvbuf(stdout,NULL,_IONBF,0);
#ifdef EQ_TUNER
    need(argc==7,"MODE PRIVATE IMAGE DIRECTORY AUTHORIZATION SHA256");
    expected_image_hash=argv[6];
#else
    need(argc==5||argc==6,"MODE PRIVATE CAPS DIRECTORY [AUTHORIZATION]");
#endif
    const char *mode=argv[1];session_dir=argv[4];
    if(!strcmp(mode,"enumerate")){
      libusb_context *ctx=NULL;need(!libusb_init(&ctx),"enumeration init failed");libusb_device **list=NULL;
      ssize_t n=libusb_get_device_list(ctx,&list);need(n>=0,"enumeration list failed");
      for(ssize_t i=0;i<n;i++){struct libusb_device_descriptor d;need(!libusb_get_device_descriptor(list[i],&d),"enumeration descriptor failed");printf("USB_ID=%04x:%04x bus=%u address=%u\n",d.idVendor,d.idProduct,libusb_get_bus_number(list[i]),libusb_get_device_address(list[i]));}
      libusb_free_device_list(list,1);libusb_exit(ctx);puts("MACOS_PHASE_OK=enumerate");return 0;
    }
    if(!strcmp(mode,"stable-programmer")){
      libusb_context *ctx=NULL;need(!libusb_init(&ctx),"read-only enumeration init failed");
      stable_programmer(ctx,0,NULL);libusb_exit(ctx);puts("MACOS_PHASE_OK=stable-programmer-read-only");return 0;
    }
    int normal=!strcmp(mode,"normal-read")||!strcmp(mode,"normal-read-B")||!strcmp(mode,"normal-read-any")||!strcmp(mode,"identify-normal")||!strcmp(mode,"actual-descriptor")||!strcmp(mode,"transition-read")||!strcmp(mode,"transition-read-B")||!strcmp(mode,"ota-A")||!strcmp(mode,"ota-B")||!strcmp(mode,"probe");
    int audit=!strcmp(mode,"read-bootstrap")||!strcmp(mode,"read-running");
    int baseline=!strcmp(mode,"verify-baseline");
    int write=!strcmp(mode,"stage-running")||!strcmp(mode,"activate-running")||!strcmp(mode,"recover-running")||!strcmp(mode,"recover-B-running");
    need(normal||audit||write||baseline||!strcmp(mode,"detect-programmer"),"unknown native mode");
#ifdef CAPS_READ_ONLY
    need(!write&&strcmp(mode,"probe"),"read-only binary rejects persistent phases and unapproved custom probe");
#else
    if(write||!strcmp(mode,"probe")){
#ifdef EQ_TUNER
      const char *token=!strcmp(mode,"stage-running")?"STAGE-EQ-B":!strcmp(mode,"activate-running")?"ACTIVATE-EQ-B":(!strcmp(mode,"recover-running")||!strcmp(mode,"recover-B-running"))?"RECOVER-VERIFIED-A":"GET-EOIC-CAPS";
#else
      const char *token=!strcmp(mode,"stage-running")?"STAGE-CAPS-B":!strcmp(mode,"activate-running")?"ACTIVATE-CAPS-B":(!strcmp(mode,"recover-running")||!strcmp(mode,"recover-B-running"))?"RECOVER-VERIFIED-A":"GET-EOIC-CAPS";
#endif
      need(argc==
#ifdef EQ_TUNER
           7
#else
           6
#endif
           &&!strcmp(argv[5],token),"explicit phase authorization required");
    }
#endif
    assets(argv[2],argv[3]);libusb_context *ctx=NULL;libusb_device_handle *h=NULL;
    if(!strcmp(mode,"activate-running"))native_open_stable_programmer(&ctx,&h);
    else native_open(!normal,&ctx,&h);
    if(!strcmp(mode,"transition-read")||!strcmp(mode,"transition-read-B")){
      enter(h,!strcmp(mode,"transition-read")?'A':'B');libusb_close(h);h=capture_programmer(ctx);puts("VID:PID=be57:0101");native_read_all(h,1);goto done;
    }
    if(!strcmp(mode,"actual-descriptor")){
      uint8_t d[18];int n=libusb_control_transfer(h,0x80,6,0x0100,0,d,18,2000);need(n==18&&d[0]==18&&d[1]==1,"actual device descriptor failed");loghex("DIRECT_DEVICE_DESCRIPTOR=",d,18);printf("DIRECT_VID:PID=%04x:%04x\n",d[8]|d[9]<<8,d[10]|d[11]<<8);goto done;
    }
    if(!strcmp(mode,"detect-programmer")){descriptors(h,1);goto done;}
    if(!strcmp(mode,"normal-read")){descriptors(h,0);normal_query(h,'A');goto done;}
    if(!strcmp(mode,"normal-read-B")){descriptors(h,0);normal_query(h,'B');goto done;}
    if(!strcmp(mode,"normal-read-any")){descriptors(h,0);normal_query_any(h);goto done;}
    if(!strcmp(mode,"identify-normal")){normal_query_any(h);goto done;}
    if(!strcmp(mode,"ota-A")||!strcmp(mode,"ota-B")){enter(h,!strcmp(mode,"ota-A")?'A':'B');goto done;}
    if(audit){native_read_all(h,!strcmp(mode,"read-bootstrap"));goto done;}
    if(baseline){
      need(argc==6,"baseline snapshot path required");uint8_t *expected=locked_file(argv[5],FLASH_SIZE,"077317b51d1df4b358603fafc690a92e8bc5a17f116c24d3edf9223c4ae150e2");
      descriptors(h,1);int cs=cdc_setup(h);need(cs>=0,"native CDC reopen failed");
      uint8_t *b=malloc(0x4a000);need(b!=NULL,"allocation");need(!read_range(h,FLAG_ADDR,b,0x4a000),"protected flags/A/B read failed");save("protected-readback.bin",b,0x4a000);need(!memcmp(b,expected+0x4000,0x4a000),"protected state differs from captured baseline");free(b);
      uint8_t nv[4096];need(!read_range(h,0x3c07d000,nv,4096),"NV sector read failed");save("nv-readback.bin",nv,4096);need(!memcmp(nv,expected+0x7d000,4096),"NV record changed since capture");
      free(expected);puts("NATIVE_REOPEN_PROTECTED_READBACK=VERIFIED");cdc_release(h,cs);goto done;
    }
#ifndef CAPS_READ_ONLY
    if(!strcmp(mode,"probe")){
      uint8_t b[12];const uint8_t expected[12]={'E','O','I','C',1,0,8,0,0,0,0,0};
      need(libusb_control_transfer(h,0xc0,0xe0,0x454f,0x4943,b,12,1000)==12&&!memcmp(b,expected,12),"CAPS reply differs");loghex("CAPS_RESPONSE=",b,12);goto done;
    }
    descriptors(h,1);int cs=cdc_setup(h);need(cs>=0,"native CDC setup failed");
    verify_a(h,"a-before.bin");uint8_t before[8192];flags(h,before,"flags-before.bin");
    if(!strcmp(mode,"stage-running")){
      need(a_flag(before),"stage requires A selected");
      uint8_t *baseline,*current;
#ifdef EQ_TUNER
      baseline=whole_flash(h,"flash-before-stage.bin");
      need(!memcmp(baseline+0x6000,authority+0x6000,A_BYTES),"complete recovery A differs before stage");
      need(flag_is(baseline+0x4000,'A'),"active flag is not A before stage");
      char prepared_path[4096];int prepared_len=snprintf(prepared_path,sizeof(prepared_path),"%s/../prepare/flash-current.bin",session_dir);
      need(prepared_len>0&&prepared_len<(int)sizeof(prepared_path),"prepared flash path too long");
      size_t prepared_size=0;uint8_t *prepared=readfile(prepared_path,&prepared_size);
      need(prepared&&prepared_size==FLASH_SIZE,"read-only A/B preflight capture missing");
      need(!memcmp(baseline,prepared,FLASH_SIZE),"flash state changed after pre-write preflight");
      free(prepared);
      save("flash-backup-before-stage.bin",baseline,FLASH_SIZE);
#else
      baseline=validated_baseline();current=whole_flash(h,"flash-before-stage.bin");
      need(!memcmp(current,baseline,FLASH_SIZE),"live full flash differs from approved read-only baseline");free(current);
#endif
      need(!stage_image(h,caps_image,CAPS_BYTES,B_START,36864),"stage failed; no activation");
      verify_b(h,"b-staged.bin");verify_a(h,"a-after.bin");uint8_t after[8192];flags(h,after,"flags-after.bin");need(!memcmp(before,after,8192),"flags changed during stage");puts("CAPS_BOOT_FLAGS_UNCHANGED=YES");
      current=whole_flash(h,"flash-after-stage.bin");
#ifdef EQ_TUNER
      need(!memcmp(current,baseline,0x2e000)&&!memcmp(current+0x4e000,baseline+0x4e000,FLASH_SIZE-0x4e000),"flash outside B sector envelope changed");
      free(baseline);
#else
      need(!memcmp(current,baseline,0x2e000)&&!memcmp(current+0x4e000,baseline+0x4e000,FLASH_SIZE-0x4e000),"flash outside B sector envelope changed");free(baseline);puts("MACOS_FLASH_OUTSIDE_B_UNCHANGED=YES");
#endif
      free(current);puts("MACOS_FLASH_OUTSIDE_B_UNCHANGED=YES");
    }else if(!strcmp(mode,"activate-running")){
      need(a_flag(before),"activation requires A selected");verify_b(h,"b-before.bin");
      char p[4096];pathjoin(p,session_dir,"../stage/flags-before.bin");size_t n=0;uint8_t *old=readfile(p,&n);need(old&&n==8192&&!memcmp(old,before,8192),"flags differ from staging session");free(old);switch_flag(h,before,'B',1);
    }else{
      if(!strcmp(mode,"recover-B-running"))need(flag_is(before,'B'),"B-to-A recovery requires active boot flag B");
      if(a_flag(before)){uint8_t after[8192];flags(h,after,"flags-after.bin");need(!memcmp(before,after,8192),"A-selected flags changed");puts("CAPS_ALREADY_A=YES no write");}
      else switch_flag(h,before,'A',0);
    }
    cdc_release(h,cs);
#endif
done:
    printf("MACOS_PHASE_OK=%s\n",mode);libusb_close(h);libusb_exit(ctx);free(authority);free(caps_image);return 0;
}
