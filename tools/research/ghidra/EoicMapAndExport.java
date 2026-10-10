// @category EOIC
// Map the firmware's startup-copied segments into executable/data aliases and
// export only the startup and EQ/USB-audio functions relevant to the report.
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.address.AddressSetView;
import ghidra.program.model.lang.Register;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.FunctionIterator;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.listing.Listing;
import ghidra.program.model.mem.Memory;
import ghidra.program.model.mem.MemoryBlock;
import ghidra.program.model.symbol.Reference;
import java.io.BufferedWriter;
import java.io.FileWriter;
import java.math.BigInteger;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

public class EoicMapAndExport extends GhidraScript {
    private long number(String text) { return Long.decode(text); }
    private String hex(long value) { return String.format("0x%08x", value); }
    private static final Pattern LITERAL_OPERAND = Pattern.compile("\\[(0x[0-9a-fA-F]+)\\]");

    @Override
    protected void run() throws Exception {
        String[] args = getScriptArgs();
        if (args.length != 7) {
            throw new IllegalArgumentException("args: flashBase ramBase codeBase segments seeds outputPath targets");
        }
        long flashBase = number(args[0]);
        long ramBase = number(args[1]);
        long codeBase = number(args[2]);
        String[] segmentArgs = args[3].split(",");
        String[] seedArgs = args[4].split(",");
        String[] targetArgs = args[6].split(",");
        Memory memory = currentProgram.getMemory();
        AddressSpaceDefault space = new AddressSpaceDefault();

        // The raw import is the physical flash image at its documented base.
        // Copy the initialized segments to both the execution and data aliases.
        for (int i = 0; i < segmentArgs.length; i++) {
            String[] fields = segmentArgs[i].split(":");
            long source = number(fields[0]);
            long end = number(fields[1]);
            long dataAddress = number(fields[2]);
            int size = Math.toIntExact(end - source);
            byte[] bytes = new byte[size];
            memory.getBytes(space.addr(flashBase + source), bytes);

            Address dataStart = space.addr(dataAddress);
            MemoryBlock dataBlock = memory.createInitializedBlock(
                "ram_data_" + i, dataStart, size, (byte) 0, monitor, false);
            dataBlock.setPermissions(true, true, false);
            memory.setBytes(dataStart, bytes);

            long executionAddress = codeBase + dataAddress - ramBase;
            Address codeStart = space.addr(executionAddress);
            MemoryBlock codeBlock = memory.createInitializedBlock(
                "ram_exec_" + i, codeStart, size, (byte) 0, monitor, false);
            codeBlock.setPermissions(true, false, true);
            memory.setBytes(codeStart, bytes);
        }

        Register thumb = currentProgram.getProgramContext().getRegister("TMode");
        if (thumb == null) throw new IllegalStateException("ARM TMode context register unavailable");
        // The copied-code alias is Thumb. The flash-resident reset/copy stub is
        // also Thumb; setting context is not the same as declaring all bytes code.
        for (int i = 0; i < segmentArgs.length; i++) {
            String[] fields = segmentArgs[i].split(":");
            long size = number(fields[1]) - number(fields[0]);
            long executionAddress = codeBase + number(fields[2]) - ramBase;
            currentProgram.getProgramContext().setValue(
                thumb, space.addr(executionAddress), space.addr(executionAddress + size - 1), BigInteger.ONE);
        }
        MemoryBlock[] blocks = memory.getBlocks();
        for (MemoryBlock block : blocks) {
            if (block.getStart().getOffset() == flashBase) {
                block.setPermissions(true, false, true);
                long end = block.getEnd().getOffset();
                currentProgram.getProgramContext().setValue(
                    thumb, block.getStart().add(0x10), block.getEnd(), BigInteger.ONE);
            }
        }

        // Seed exact addresses recovered by the prior hash-keyed indexes.
        StringBuilder seedReport = new StringBuilder();
        for (String item : seedArgs) {
            String[] fields = item.split(":", 2);
            Address entry = space.addr(number(fields[0]));
            String name = fields.length > 1 ? fields[1] : "";
            try {
                disassemble(entry);
                Function function = currentProgram.getFunctionManager().getFunctionAt(entry);
                if (function == null) function = createFunction(entry, name.isEmpty() ? null : name);
                else if (!name.isEmpty() && function.getName().startsWith("FUN_")) function.setName(name, ghidra.program.model.symbol.SourceType.USER_DEFINED);
                seedReport.append(hex(entry.getOffset())).append(" ").append(name)
                    .append(" function=").append(function == null ? "none" : function.getName()).append("\n");
            } catch (Exception e) {
                seedReport.append(hex(entry.getOffset())).append(" ").append(name)
                    .append(" ERROR ").append(e.toString()).append("\n");
            }
        }

        // Export the targeted mapped regions, reference hits and discovered
        // functions. Output goes only to ignored research/cache.
        try (BufferedWriter out = new BufferedWriter(new FileWriter(args[5]))) {
            out.write("program=" + currentProgram.getName() + "\n");
            out.write("language=" + currentProgram.getLanguageID() + "\n");
            out.write("flash_base=" + hex(flashBase) + "\n");
            out.write("ram_base=" + hex(ramBase) + "\ncode_alias_base=" + hex(codeBase) + "\n");
            out.write("segments=" + args[3] + "\n\nSEEDS\n" + seedReport + "\n");

            out.write("MEMORY_BLOCKS\n");
            for (MemoryBlock block : memory.getBlocks()) {
                out.write(block.getName() + " " + block.getStart() + ".." + block.getEnd()
                    + " r=" + block.isRead() + " w=" + block.isWrite() + " x=" + block.isExecute() + "\n");
            }

            Listing listing = currentProgram.getListing();
            FunctionIterator functions = currentProgram.getFunctionManager().getFunctions(true);
            out.write("\nDISCOVERED_FUNCTIONS\n");
            while (functions.hasNext()) {
                Function function = functions.next();
                long addr = function.getEntryPoint().getOffset();
                if (!inMappedAlias(addr, segmentArgs, codeBase, ramBase) &&
                    !(addr >= flashBase && addr < flashBase + 0x8000)) continue;
                out.write(function.getEntryPoint() + " " + function.getName() + " size=" + function.getBody().getNumAddresses() + "\n");
            }

            out.write("\nTARGET_REFERENCES\n");
            for (String targetText : targetArgs) {
                Address target = space.addr(number(targetText));
                out.write("TARGET " + target + "\n");
                for (Reference ref : currentProgram.getReferenceManager().getReferencesTo(target)) {
                    out.write("  " + ref.getFromAddress() + " " + ref.getReferenceType() + " operand=" + ref.getOperandIndex() + "\n");
                }
            }

            out.write("\nRESOLVED_LITERAL_POINTERS\n");
            functions = currentProgram.getFunctionManager().getFunctions(true);
            while (functions.hasNext()) {
                Function function = functions.next();
                long addr = function.getEntryPoint().getOffset();
                if (!inMappedAlias(addr, segmentArgs, codeBase, ramBase) &&
                    !(addr >= flashBase && addr < flashBase + 0x8000)) continue;
                for (Instruction instruction : listing.getInstructions(function.getBody(), true)) {
                    // On raw imports Ghidra may not materialize a literal-pool
                    // reference for every ARM PC-relative LDR. Recover the
                    // address rendered in the operand and read the mapped word
                    // directly, while retaining references for target xrefs.
                    if (function.getEntryPoint().getOffset() >= flashBase &&
                        function.getEntryPoint().getOffset() < flashBase + 0x8000 &&
                        instruction.getMnemonicString().toLowerCase().startsWith("ldr")) {
                        Matcher literal = LITERAL_OPERAND.matcher(instruction.toString());
                        if (literal.find()) {
                            Address pool = space.addr(number(literal.group(1)));
                            if (memory.contains(pool)) {
                                try {
                                    long value = Integer.toUnsignedLong(memory.getInt(pool));
                                    out.write("STARTUP_LITERAL " + instruction.getAddress() + " "
                                        + instruction.toString() + " pool=" + pool + " value=" + hex(value) + "\n");
                                } catch (Exception ignored) { }
                            }
                        }
                    }
                    for (Reference ref : currentProgram.getReferenceManager().getReferencesFrom(instruction.getAddress())) {
                        Address pool = ref.getToAddress();
                        if (!instruction.getMnemonicString().toLowerCase().startsWith("ldr") ||
                            !memory.contains(pool) || pool.equals(instruction.getAddress())) continue;
                        try {
                            long value = Integer.toUnsignedLong(memory.getInt(pool));
                            for (String targetText : targetArgs) {
                                long wanted = number(targetText);
                                boolean direct = value == wanted;
                                boolean oneHop = false;
                                if (!direct && memory.contains(space.addr(value)) && (value & 3) == 0) {
                                    oneHop = Integer.toUnsignedLong(memory.getInt(space.addr(value))) == wanted;
                                }
                                if (direct || oneHop) {
                                    out.write(function.getEntryPoint() + " " + instruction.getAddress() + " "
                                        + instruction.toString() + " pool=" + pool + " value=" + hex(value)
                                        + (oneHop ? " -> *" + hex(value) : "") + " target=" + targetText
                                        + " ref=" + ref.getReferenceType() + "\n");
                                }
                            }
                        } catch (Exception ignored) { }
                    }
                }
            }

            out.write("\nTARGETED_DISASSEMBLY\n");
            functions = currentProgram.getFunctionManager().getFunctions(true);
            int instructionCount = 0;
            while (functions.hasNext() && instructionCount < 24000) {
                Function function = functions.next();
                long addr = function.getEntryPoint().getOffset();
                if (!inMappedAlias(addr, segmentArgs, codeBase, ramBase) &&
                    !(addr >= flashBase && addr < flashBase + 0x8000)) continue;
                out.write("\nFUNCTION " + function.getEntryPoint() + " " + function.getName() + "\n");
                for (Instruction instruction : listing.getInstructions(function.getBody(), true)) {
                    out.write(instruction.getAddress() + " " + instruction.toString() + "\n");
                    instructionCount++;
                    if (instructionCount >= 24000) break;
                }
            }
            out.write("\ninstruction_export_count=" + instructionCount + "\n");
        }
        println("EOIC_GHIDRA_EXPORT=" + args[5]);
    }

    private boolean inMappedAlias(long address, String[] segmentArgs, long codeBase, long ramBase) {
        for (String item : segmentArgs) {
            String[] fields = item.split(":");
            long start = codeBase + number(fields[2]) - ramBase;
            long end = start + number(fields[1]) - number(fields[0]);
            if (address >= start && address < end) return true;
        }
        return false;
    }

    private class AddressSpaceDefault {
        Address addr(long value) { return currentProgram.getAddressFactory().getDefaultAddressSpace().getAddress(value); }
    }
}
