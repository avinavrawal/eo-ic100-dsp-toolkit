"""CPU harness for authored extension and stock routines. No real USB/MMIO.

Mapped peripherals are simulated memory; completion latch/timer are modeled.
This validates CPU/data flow and cannot validate analog DSP or actual timing.
"""
import json
import math
import struct
import sys
from collections import deque
from pathlib import Path
from custom_vendor_patch import OUT,ROOT,ram_image,FLASH_BASE,CODE_BASE,INJECT_CODE

sys.path.insert(0,str(OUT/'deps'))
from unicorn import Uc,UC_ARCH_ARM,UC_MODE_THUMB,UC_MODE_MCLASS,UC_HOOK_CODE,UC_HOOK_MEM_READ,UC_HOOK_MEM_WRITE,UC_HOOK_MEM_INVALID
from unicorn.arm_const import *

STOP=0x10000000
FRAME=0x21000000
ARGS=FRAME+0x100
PAYLOAD=FRAME+0x200


class Machine:
    def __init__(self,variant='eq-test',ack_mode='auto'):
        self.variant=variant
        self.ack_mode=ack_mode
        self.ack_reads=0
        self.report=json.loads((OUT/(variant+'-report.json')).read_text())
        self.image=(OUT/(variant+'.bin')).read_bytes()
        self.uc=Uc(UC_ARCH_ARM,UC_MODE_THUMB|UC_MODE_MCLASS)
        self.uc.ctl_set_cpu_model(UC_CPU_ARM_CORTEX_M4)
        for base,size in [(CODE_BASE,0x20000),(FLASH_BASE,0x20000),
                          (0x00200000,0x40000),(0x20000000,0x40000),
                          (FRAME,0x1000),(STOP,0x1000),(0x40000000,0x400000),(0xe000e000,0x2000)]:
            self.uc.mem_map(base,size)
        self.uc.mem_write(CODE_BASE,self.image[:-4]); self.uc.mem_write(FLASH_BASE,self.image[:-4])
        ram=ram_image(self.image)
        self.uc.mem_write(0x00200000,bytes(ram)); self.uc.mem_write(0x20000000,bytes(ram))
        self.uc.reg_write(UC_ARM_REG_C1_C0_2,0x00f00000)
        self.uc.reg_write(UC_ARM_REG_FPEXC,0x40000000)
        self.uc.hook_add(UC_HOOK_CODE,self._code)
        self.uc.hook_add(UC_HOOK_MEM_READ,self._read)
        self.uc.hook_add(UC_HOOK_MEM_WRITE,self._write)
        self.uc.hook_add(UC_HOOK_MEM_INVALID,self._invalid)
        self.calls=[]; self.writes=[]; self.count=0; self.tick=0
        self.trace=deque(maxlen=8)
        self.stubs={0x00205534:0,0x002056b8:0}  # reviewed printf/assert diagnostics
        self.eq_args=[]
        self.math_models={0x002141d8:'pow',0x002141a0:'sqrt',0x002141c0:'sin',0x002141a8:'cos'}
        # Model reviewed usb_audio_open callback/buffer registration, not a boot.
        self.uc.mem_write(0x2001b15c,struct.pack('<I',int(self.report['hooks']['vendor']['new'],16)))
        self.uc.mem_write(0x2001b160,struct.pack('<I',0x20019804 if variant.startswith('eq-diagnostic') else PAYLOAD))
        self.uc.mem_write(0x2001b164,struct.pack('<I',240))
        self.uc.mem_write(0x2001ab9c,bytes(ram[0x150ac:0x150ac+40]))
        self.uc.mem_write(0x2001abef,b'\x04')

    def _invalid(self,uc,access,address,size,value,_):
        print('UNMAPPED',hex(address),'PC',hex(uc.reg_read(UC_ARM_REG_PC)),
              'R0..3',[hex(uc.reg_read(UC_ARM_REG_R0+i)) for i in range(4)],flush=True)
        print('recent',list(self.trace),flush=True)
        return False

    def _code(self,uc,address,size,_):
        self.count+=1
        self.trace.append([hex(address),hex(uc.reg_read(UC_ARM_REG_R3))])
        if address==STOP: uc.emu_stop(); return
        if address in [0x0020dd10,0x0020d998,0x0020a938,0x0020a178,0x0020a424]:
            self.calls.append(hex(address))
        if address==0x0020a938:
            r1=uc.reg_read(UC_ARM_REG_R1)
            self.eq_args.append(dict(r0=uc.reg_read(UC_ARM_REG_R0),r2=uc.reg_read(UC_ARM_REG_R2),
                                     cfg=bytes(uc.mem_read(r1,140)).hex()))
        if address in self.stubs:
            uc.reg_write(UC_ARM_REG_R0,self.stubs[address]); uc.reg_write(UC_ARM_REG_PC,uc.reg_read(UC_ARM_REG_LR))
        if address in self.math_models:
            # Pure math library model. Coefficient generator/setter remain guest
            # code; this does not claim emulation of the vendor libm internals.
            x=struct.unpack('<d',struct.pack('<Q',uc.reg_read(UC_ARM_REG_D0)))[0]
            y=struct.unpack('<d',struct.pack('<Q',uc.reg_read(UC_ARM_REG_D1)))[0]
            name=self.math_models[address]
            value=math.pow(x,y) if name=='pow' else getattr(math,name)(x)
            uc.reg_write(UC_ARM_REG_D0,struct.unpack('<Q',struct.pack('<d',value))[0])
            uc.reg_write(UC_ARM_REG_PC,uc.reg_read(UC_ARM_REG_LR))

    def _read(self,uc,access,address,size,value,_):
        if address==0x403000e0:
            old=struct.unpack('<I',uc.mem_read(address,4))[0]
            self.ack_reads+=1
            # Setter selects a bank with bit 22 and polls bit 24 until it
            # matches that selection, in either direction.
            if self.ack_mode=='stuck-low': acknowledged=old&~(1<<24)
            elif self.ack_mode=='stuck-high': acknowledged=old|(1<<24)
            else: acknowledged=(old|(1<<24)) if old&(1<<22) else (old&~(1<<24))
            uc.mem_write(address,struct.pack('<I',acknowledged))
        if address==0x40004004:
            self.tick=(self.tick+16000)&0xffffffff
            uc.mem_write(address,struct.pack('<I',(-self.tick)&0xffffffff))

    def _write(self,uc,access,address,size,value,_):
        if 0x40000000<=address<0x40400000:
            self.writes.append(dict(address=hex(address),size=size,value=hex(value)))

    def call(self,address,*args):
        uc=self.uc
        for i,value in enumerate(args):uc.reg_write(UC_ARM_REG_R0+i,value)
        uc.reg_write(UC_ARM_REG_SP,0x20030000)
        uc.reg_write(UC_ARM_REG_LR,STOP|1)
        self.count=0
        try:
            uc.emu_start(address|1,STOP,count=1000000)
        except Exception:
            print('EMULATION-ERROR',hex(uc.reg_read(UC_ARM_REG_PC)),
                  'R0..3',[hex(uc.reg_read(UC_ARM_REG_R0+i)) for i in range(4)],
                  'recent',list(self.trace),flush=True)
            raise
        if uc.reg_read(UC_ARM_REG_PC)!=STOP: raise RuntimeError('instruction limit reached: '+str(list(self.trace)))
        return uc.reg_read(UC_ARM_REG_R0)

    def activate_audio(self,rate=48000):
        self.uc.mem_write(0x200162c8,struct.pack('<I',rate))
        self.uc.mem_write(0x200162cd,b'\x01')
        self.uc.mem_write(0x200162b8,struct.pack('<I',1))

    def setup(self,bm=0xc0,request=0xe0,value=0x454f,index=0x4943,length=12):
        self.uc.mem_write(FRAME,b'\0'*20)
        self.uc.mem_write(FRAME+12,struct.pack('<BBHHH',bm,request,value,index,length))
        result=self.call(int(self.report['hooks']['setup']['new'],16),FRAME)
        frame=bytes(self.uc.mem_read(FRAME,20))
        state=frame[0]; pointer=struct.unpack_from('<I',frame,4)[0]; n=struct.unpack_from('<H',frame,8)[0]
        payload=bytes(self.uc.mem_read(pointer,n)) if pointer and n and state==4 else b''
        return dict(result=result,state=state,pointer=pointer,length=n,payload=payload.hex())

    def core_setup(self,bm=0xc0,request=0xe0,value=0x454f,index=0x4943,length=12):
        # Populate the reviewed setup DMA buffer/remaining-byte position and
        # execute the actual endpoint-zero state handler, including RAM copy
        # into its transmit DMA buffer. Controller MMIO is simulated.
        self.uc.mem_write(0x2001ac74,b'\0'*20)
        self.uc.mem_write(0x2001ac44,struct.pack('<BBHHH',bm,request,value,index,length))
        self.uc.mem_write(0x40180b10,struct.pack('<I',0x28))
        self.call(0x00206131,0,9)
        frame=bytes(self.uc.mem_read(0x2001ac74,20))
        n=struct.unpack_from('<H',frame,8)[0]
        return dict(state=frame[0],length=n,dma_payload=bytes(self.uc.mem_read(0x2001abf4,min(n,64))).hex())

    def vendor(self,payload=b'',bm=0x40,request=0xe1,value=0x454f,index=0x4943,length=None):
        if length is None:length=len(payload)
        self.uc.mem_write(FRAME+12,struct.pack('<BBHHH',bm,request,value,index,length))
        if payload:self.uc.mem_write(PAYLOAD,payload)
        self.uc.mem_write(ARGS,struct.pack('<IIHH',FRAME+12,PAYLOAD if payload else 0,len(payload),0))
        return self.call(int(self.report['hooks']['vendor']['new'],16),ARGS)

    def receive(self,payload,pointer=PAYLOAD):
        self.uc.mem_write(pointer,payload)
        self.uc.mem_write(FRAME+4,struct.pack('<IHH',pointer,len(payload),0))
        result=self.call(int(self.report['hooks'].get('data',{'new':'0x20e5fd'})['new'],16),FRAME)
        return dict(result=result,state=self.uc.mem_read(FRAME,1)[0])


if __name__=='__main__':
    if '--tests' in sys.argv:
        import unittest
        suite=unittest.defaultTestLoader.discover(str(Path(__file__).parent),pattern='test_custom_vendor.py')
        suite.addTests(unittest.defaultTestLoader.discover(
            str(Path(__file__).parent),pattern='test_custom_vendor_diagnostic.py'))
        result=unittest.TextTestRunner(verbosity=1).run(suite)
        report=dict(tests=result.testsRun,failures=len(result.failures),errors=len(result.errors),
                    scope='custom EQ and diagnostic Thumb CPU suites; modeled registration/MMIO, pure libm; no device transport')
        (OUT/'test-results.json').write_text(json.dumps(report,indent=2)+'\n')
        sys.exit(not result.wasSuccessful())
    machine=Machine('caps-only')
    print('CAPS',machine.setup())
    machine=Machine();machine.activate_audio()
    print('gain',machine.vendor(struct.pack('<f',-1)))
    print('calls',machine.calls,'MMIO writes',len(machine.writes),'instructions',machine.count)
