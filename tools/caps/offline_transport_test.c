/* RAM-only fake device. This executable is NOT the physical transport helper.
 * Tests main/check ordering; no libusb function is reached by these entry points.
 */
#include "sha256.h"
#include "protocol.c"
static uint8_t fake_flash[FLASH_SIZE];
static const char *fault;
static const char *test_mode;
static int pending;
static int fake_set_option(libusb_context *c,enum libusb_option o,...){(void)c;(void)o;return 0;}
static int fake_init(libusb_context **c){*c=(libusb_context*)1;return 0;}
static int fake_wrap(libusb_context *c,intptr_t fd,libusb_device_handle **h){(void)c;(void)fd;*h=(libusb_device_handle*)1;return 0;}
static libusb_device *fake_device(libusb_device_handle *h){(void)h;return (libusb_device*)1;}
static int fake_descriptor(libusb_device *d,struct libusb_device_descriptor *v){(void)d;memset(v,0,sizeof(*v));int normal=strstr(test_mode,"enter")||strstr(test_mode,"query")||!strcmp(test_mode,"probe");v->idVendor=normal?VID_NORMAL:VID_CDC;v->idProduct=normal?PID_NORMAL:PID_CDC;if(!strcmp(fault,"identity"))v->idProduct=0x9999;return 0;}
static void fake_close(libusb_device_handle *h){(void)h;}
static void fake_exit(libusb_context *c){(void)c;}
static int fake_cdc(libusb_device_handle *h){(void)h;return 0;}
static void fake_release(libusb_device_handle *h,int s){(void)h;(void)s;}
static int fake_bootstrap(libusb_device_handle *h,const char *p,uint32_t *s){(void)h;(void)p;*s=36864;return strcmp(fault,"bootstrap")==0?-1:0;}
static int fake_read(libusb_device_handle *h,uint32_t addr,uint8_t *b,size_t n){
    (void)h;if(addr<FLASH_BASE||n>FLASH_SIZE||addr-FLASH_BASE>FLASH_SIZE-n)return -1;
    if(!strcmp(fault,"A-read")&&addr==A_START)return -1;
    memcpy(b,fake_flash+addr-FLASH_BASE,n);if(!strcmp(fault,"A-corrupt")&&addr==A_START)b[100]^=1;
    if(!strcmp(fault,"B-corrupt")&&addr==B_START)b[100]^=1;
    return 0;
}
static int fake_stage(libusb_device_handle *h,const uint8_t *b,size_t n,uint32_t addr,uint32_t s){
    (void)h;if(addr!=B_START||n!=0x20004||s!=36864)return -1;
    puts("TEST_WRITE=B");memcpy(fake_flash+addr-FLASH_BASE,b,n-4);memcpy(fake_flash+addr-FLASH_BASE,VALID_MAGIC,4);if(!strcmp(fault,"post-stage-outside"))fake_flash[0x7d010]^=1;return 0;
}
static int fake_control(libusb_device_handle *h,uint8_t type,uint8_t request,uint16_t value,uint16_t index,unsigned char *b,uint16_t n,unsigned timeout){
    (void)h;(void)timeout;printf("TEST_CONTROL=%02x/%02x/%04x/%04x/%u\n",type,request,value,index,n);
    if(type==0xc0&&request==0xe0&&value==0x454f&&index==0x4943&&n==12){const uint8_t reply[12]={'E','O','I','C',1,0,8,0,0,0,0,0};memcpy(b,reply,12);if(!strcmp(fault,"CAPS"))b[8]=1;return 12;}
    if(type==0x40&&request==6){
      if(n==12&&!memcmp(b,"QUERY_SW_VER",12))pending=1;
      else if(n==5&&!memcmp(b,"CHECK",5))pending=2;
      else if(n==9&&!memcmp(b,"FW_UPDATE",9)){puts("TEST_VENDOR_MUTATION=FW_UPDATE");pending=3;}
      else if(n==10&&!memcmp(b,"SYS_REBOOT",10)){puts("TEST_VENDOR_MUTATION=SYS_REBOOT");pending=4;}
      else return -999;return n;
    }
    if(type==0xc0&&request==12){
      if(pending==1&&n==14){const char *version=!strcmp(fault,"version")||strstr(test_mode,"-B")?"0.23_051101_ab":"0.04_051101_aa";memcpy(b,version,14);return 14;}
      if(pending==2&&n==3){memcpy(b,!strcmp(fault,"CHECK")?"9.9":"1.1",3);return 3;}
      if(pending==3&&n==1){b[0]='1';return 1;}
      if(pending==4&&n==1)return -4;
    }
    return -999;
}
static int fake_erase(libusb_device_handle *h,uint32_t addr,uint8_t seq){
    (void)h;(void)seq;if(addr!=FLAG_ADDR&&addr!=BACKUP_FLAG_ADDR)return -1;
    printf("TEST_ERASE=%08x\n",addr);memset(fake_flash+addr-FLASH_BASE,0xff,4096);return 0;
}
static int fake_write(libusb_device_handle *h,uint32_t addr,uint8_t seq,const uint8_t b[8]){
    (void)h;(void)seq;if(addr!=FLAG_ADDR&&addr!=BACKUP_FLAG_ADDR)return -1;
    printf("TEST_WRITE=%08x\n",addr);memcpy(fake_flash+addr-FLASH_BASE,b,8);return 0;
}
#define CAPS_PROTOCOL_IMPORTED
#define libusb_set_option fake_set_option
#define libusb_init fake_init
#define libusb_wrap_sys_device fake_wrap
#define libusb_get_device fake_device
#define libusb_get_device_descriptor fake_descriptor
#define libusb_close fake_close
#define libusb_exit fake_exit
#define libusb_control_transfer fake_control
#define cdc_setup fake_cdc
#define cdc_release fake_release
#define bootstrap_programmer fake_bootstrap
#define read_range fake_read
#define stage_image fake_stage
#define erase_flag_at fake_erase
#define write_flag_bytes_at fake_write
#define main caps_entry_not_physical
#include "caps_transport.c"
#undef main
#ifndef CAPS_NATIVE_OFFLINE
int main(int argc,char **argv){
    if(argc!=6)return 2;test_mode=argv[1];fault=getenv("CAPS_TEST_FAULT");if(!fault)fault="none";
    size_t n=0;char p[4096];snprintf(p,sizeof(p),"%s/flash-backup.bin",argv[2]);uint8_t *original=readfile(p,&n);
    if(!original||n!=FLASH_SIZE)return 3;memcpy(fake_flash,original,n);free(original);
    if(strstr(argv[1],"activate")){uint8_t *b=readfile(argv[3],&n);if(!b||n!=0x20004)return 4;memcpy(fake_flash+0x2e000,b,n-4);memcpy(fake_flash+0x2e000,VALID_MAGIC,4);free(b);}
    if(strstr(argv[1],"recover")&&strcmp(argv[1],"recover-bootstrap-A")){memset(fake_flash+0x4000,0xff,4096);memset(fake_flash+0x4000,'B',8);}
    if(!strcmp(fault,"flag"))fake_flash[0x4000]=0;
    return caps_entry_not_physical(argc,argv);
}
#endif
