"""Host-side model for the bounded scheduler telemetry fields and ring contract."""
from dataclasses import dataclass,field

U32_MAX=0xffffffff
QUEUE_ADDRESS=0x200196ac

def sat_inc(value): return value if value>=U32_MAX else value+1
def sat_add(value,increment): return U32_MAX if increment>U32_MAX-value else value+increment

@dataclass
class Ring:
    capacity:int=30
    read:int=0
    write:int=0
    count:int=0
    highwater:int=0
    words:list=field(default_factory=lambda:[0]*30)

@dataclass
class Telemetry:
    app_loops:int=0
    consumer_calls:int=0
    event_signals:int=0
    event_bit3_clears:int=0
    busy_zero_samples:int=0
    busy_nonzero_samples:int=0
    queue_full:int=0
    command_total_ticks:int=0
    command_max_ticks:int=0
    last_tick:int=0

    def loop_sample(self,busy):
        self.app_loops=sat_inc(self.app_loops)
        if busy:self.busy_nonzero_samples=sat_inc(self.busy_nonzero_samples)
        else:self.busy_zero_samples=sat_inc(self.busy_zero_samples)
        self.consumer_calls=sat_inc(self.consumer_calls)

    def event_set(self,bit,event_word):
        if bit>31:return 1,event_word
        event_word|=1<<bit
        if bit==3:self.event_signals=sat_inc(self.event_signals)
        return 0,event_word

    def event_clear(self,bit,event_word):
        if bit>31:return 1,event_word
        mask=1<<bit
        if bit==3 and event_word&mask:self.event_bit3_clears=sat_inc(self.event_bit3_clears)
        return 0,event_word&~mask

    def push(self,ring,word,ring_address=QUEUE_ADDRESS):
        if ring.count>=ring.capacity:
            if ring_address==QUEUE_ADDRESS:self.queue_full=sat_inc(self.queue_full)
            return 1
        ring.words[ring.write]=word&U32_MAX
        ring.write+=1
        if ring.write>=ring.capacity:ring.write=0
        ring.count+=1
        ring.highwater=max(ring.highwater,ring.count)
        return 0

    def record_consumer_ticks(self,start,end):
        delta=(end-start)&U32_MAX
        self.command_total_ticks=sat_add(self.command_total_ticks,delta)
        self.command_max_ticks=max(self.command_max_ticks,delta)
        self.last_tick=end&U32_MAX
