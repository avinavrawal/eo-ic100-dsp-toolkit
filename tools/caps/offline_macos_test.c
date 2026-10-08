/* Native entry point with a RAM-only USB facade. No physical USB access. */
#define CAPS_NATIVE_OFFLINE
#include "offline_transport_test.c"
static int mock_list(libusb_context *c,libusb_device ***out){(void)c;static libusb_device *list[2]={(libusb_device*)1,NULL};*out=list;return 1;}
static void mock_free(libusb_device **d,int u){(void)d;(void)u;}
/* Stabilization logging must never dereference the fake pointer through libusb. */
static uint8_t mock_bus(libusb_device *d){(void)d;return 1;}
static uint8_t mock_address(libusb_device *d){(void)d;return 2;}
static int mock_open(libusb_device *d,libusb_device_handle **h){(void)d;*h=(libusb_device_handle*)1;return 0;}
static int mock_config(libusb_device *d,struct libusb_config_descriptor **out){
    (void)d;static struct libusb_endpoint_descriptor endpoints[2];static struct libusb_interface_descriptor alt;static struct libusb_interface interface;static struct libusb_config_descriptor config;
    endpoints[0].bEndpointAddress=0x02;endpoints[1].bEndpointAddress=0x82;endpoints[0].bmAttributes=endpoints[1].bmAttributes=2;endpoints[0].wMaxPacketSize=endpoints[1].wMaxPacketSize=64;
    alt.bInterfaceNumber=1;alt.bInterfaceClass=0x0a;alt.bNumEndpoints=2;alt.endpoint=endpoints;interface.altsetting=&alt;interface.num_altsetting=1;config.bNumInterfaces=1;config.interface=&interface;config.bConfigurationValue=1;*out=&config;return 0;
}
static void mock_free_config(struct libusb_config_descriptor *c){(void)c;}
#define libusb_get_device_list mock_list
#define libusb_free_device_list mock_free
#define libusb_get_bus_number mock_bus
#define libusb_get_device_address mock_address
#define libusb_open mock_open
#define libusb_get_active_config_descriptor mock_config
#define libusb_free_config_descriptor mock_free_config
#define MACOS_ENTRY native_entry_mocked
#include "macos_transport.c"
int main(int argc,char **argv){
    if(argc!=6)return 2;test_mode=argv[1];fault=getenv("CAPS_TEST_FAULT");if(!fault)fault="none";
    char p[4096];snprintf(p,sizeof(p),"%s/../baseline.bin",argv[4]);size_t n=0;uint8_t *baseline=readfile(p,&n);if(!baseline||n!=FLASH_SIZE)return 3;memcpy(fake_flash,baseline,n);free(baseline);
    if(!strcmp(fault,"baseline"))fake_flash[0x7d010]^=1;
    if(strstr(test_mode,"activate")){uint8_t *b=readfile(argv[3],&n);if(!b||n!=0x20004)return 4;memcpy(fake_flash+0x2e000,b,n-4);memcpy(fake_flash+0x2e000,VALID_MAGIC,4);free(b);}
    if(strstr(test_mode,"recover")){memset(fake_flash+0x4000,0xff,4096);memset(fake_flash+0x4000,'B',8);}
    return native_entry_mocked(argc,argv);
}
