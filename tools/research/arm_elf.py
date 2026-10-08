"""Small fail-closed ELF32 ARM relocatable linker for the authored extension.

No generic linker claim: only audited relocation types are supported. Output is
an explicit .text/.rodata layout, no writable allocation or unresolved symbols.
"""
import struct


def align(n, a):
    return (n+a-1)&-a


def decode_branch(code, pc):
    a,b=struct.unpack('<HH',code)
    if a & 0xf800 != 0xf000 or b & 0xd000 not in (0xd000,0x9000):
        raise ValueError('not Thumb BL/B.W')
    s=(a>>10)&1; i1=1^((b>>13)&1)^s; i2=1^((b>>11)&1)^s
    d=(s<<24)|(i1<<23)|(i2<<22)|((a&1023)<<12)|((b&2047)<<1)
    if s: d-=1<<25
    return pc+4+d


def encode_branch(pc, target, call=True):
    d=target-(pc+4)
    if pc & 1 or target & 1 or d & 1 or not -(1<<24)<=d<(1<<24):
        raise ValueError('unaligned or unreachable Thumb branch')
    d &= (1<<25)-1
    s=(d>>24)&1; i1=(d>>23)&1; i2=(d>>22)&1
    a=0xf000|(s<<10)|((d>>12)&1023)
    b=(0xd000 if call else 0x9000)|((1^i1^s)<<13)|((1^i2^s)<<11)|((d>>1)&2047)
    result=struct.pack('<HH',a,b)
    if decode_branch(result,pc)!=target: raise ValueError('branch roundtrip')
    return result


def mov_imm(a,b):
    return ((a&15)<<12)|(((a>>10)&1)<<11)|(((b>>12)&7)<<8)|(b&255)


def set_mov_imm(a,b,value):
    return (a&~0x40f)|((value>>12)&15)|(((value>>11)&1)<<10), \
           (b&~0x70ff)|(((value>>8)&7)<<12)|(value&255)


def link(raw, base):
    if raw[:7]!=b'\x7fELF\x01\x01\x01': raise ValueError('not LE ELF32')
    header=struct.unpack_from('<16sHHIIIIIHHHHHH',raw)
    if header[1]!=1 or header[2]!=40: raise ValueError('not ARM ET_REL')
    shoff, shsize, shnum, shstr=header[6],header[11],header[12],header[13]
    sections=[struct.unpack_from('<10I',raw,shoff+i*shsize) for i in range(shnum)]
    strings=raw[sections[shstr][4]:sections[shstr][4]+sections[shstr][5]]
    def string(table,offset): return table[offset:table.index(b'\0',offset)].decode()
    names=[string(strings,s[0]) for s in sections]
    addresses={}; blob=bytearray(); allocations=[]
    for i,s in enumerate(sections):
        if not s[2]&2 or s[1]==0x70000001: continue  # no ARM unwind runtime
        if s[2]&1 or s[1]!=1: raise ValueError('writable/BSS/unknown allocated section '+names[i])
        off=align(len(blob),max(4,s[8])); blob.extend(b'\xff'*(off-len(blob)))
        addresses[i]=base+off
        blob.extend(raw[s[4]:s[4]+s[5]])
        allocations.append(dict(name=names[i],address=hex(base+off),length=s[5],executable=bool(s[2]&4)))
    symidx=next(i for i,s in enumerate(sections) if s[1]==2)
    syms=sections[symidx]; table=sections[syms[6]]
    symstrings=raw[table[4]:table[4]+table[5]]
    symbols=[]; exported={}; mappings=[]
    for off in range(syms[4],syms[4]+syms[5],syms[9]):
        name,value,size,info,other,section=struct.unpack_from('<IIIBBH',raw,off)
        label=string(symstrings,name)
        address=addresses[section]+value if section in addresses else value
        symbols.append((label,address,section))
        if label.startswith(('$t','$d','$a')) and section in addresses:
            mappings.append(dict(kind=label[1],address=hex(address),section=names[section]))
        if label and section in addresses: exported[label]=dict(address=hex(address),size=size,type=info&15)
    relocations=[]
    for i,s in enumerate(sections):
        if s[1]!=9 or s[7] not in addresses: continue
        for off in range(s[4],s[4]+s[5],s[9]):
            site,info=struct.unpack_from('<II',raw,off); typ=info&255
            label,target,section=symbols[info>>8]
            if section not in addresses and section!=0xfff1: raise ValueError('unresolved '+label)
            pc=addresses[s[7]]+site; at=pc-base
            if typ==2:
                old=struct.unpack_from('<I',blob,at)[0]
                struct.pack_into('<I',blob,at,(target+old)&0xffffffff)
            elif typ in (10,30):
                old=bytes(blob[at:at+4]); addend=decode_branch(old,0)-4
                blob[at:at+4]=encode_branch(pc,(target&~1)+addend+4,typ==10)
            elif typ in (47,48):
                a,b=struct.unpack_from('<HH',blob,at)
                if a&0xfbf0 != (0xf240 if typ==47 else 0xf2c0): raise ValueError('MOV relocation opcode')
                addend=mov_imm(a,b)
                val=(target+addend) if typ==47 else (target+(addend<<16))>>16
                a,b=set_mov_imm(a,b,val&65535); struct.pack_into('<HH',blob,at,a,b)
            else: raise ValueError('unsupported ARM relocation '+str(typ))
            relocations.append(dict(site=hex(pc),type=typ,symbol=label,target=hex(target)))
    return bytes(blob),dict(base=hex(base),sections=allocations,symbols=exported,
                           mapping_symbols=mappings,relocations=relocations)
