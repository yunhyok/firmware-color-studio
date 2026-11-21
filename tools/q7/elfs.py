"""List the ELF images embedded in the firmware: headers, segments, sections, symbol counts."""
import sys, re, struct
data = open(sys.argv[1], "rb").read()
verbose = len(sys.argv) > 2
def cstr(buf, off):
    end = buf.find(b"\0", off)
    return buf[off:end].decode("latin-1")
for m in re.finditer(rb"\x7fELF\x01\x01\x01", data):
    base = m.start()
    (e_type, e_machine, e_version, e_entry, e_phoff, e_shoff, e_flags, e_ehsize, e_phentsize, e_phnum,
     e_shentsize, e_shnum, e_shstrndx) = struct.unpack_from("<HHIIIIIHHHHHH", data, base + 16)
    print(f"ELF @ {base:#x}: type {e_type} machine {e_machine} entry {e_entry:#x} phnum {e_phnum} shnum {e_shnum} shoff {e_shoff:#x}")
    if e_machine != 8 or e_phnum > 64:
        continue
    for i in range(e_phnum):
        p_type, p_offset, p_vaddr, p_paddr, p_filesz, p_memsz, p_flags, p_align = struct.unpack_from("<8I", data, base + e_phoff + i * e_phentsize)
        print(f"   seg {i}: type {p_type} off {p_offset:#x} vaddr {p_vaddr:#x} filesz {p_filesz:#x} memsz {p_memsz:#x} flags {p_flags}")
    if e_shnum == 0 or e_shentsize != 40 or e_shnum > 200 or base + e_shoff + e_shnum * 40 > len(data):
        print("   no usable section table"); continue
    sections = [struct.unpack_from("<10I", data, base + e_shoff + i * 40) for i in range(e_shnum)]
    strtab = sections[e_shstrndx]
    names = data[base + strtab[4]: base + strtab[4] + strtab[5]]
    end = 0
    for i, (name, kind, flags, addr, off, size, link, info, align, entsize) in enumerate(sections):
        label = cstr(names, name)
        end = max(end, off + (size if kind != 8 else 0))
        if verbose or kind in (2, 11) or label in (".text", ".data", ".rodata", ".bss", ".sdata") or size > 0x40000:
            print(f"   [{i:2d}] {label:22s} type {kind:2d} addr {addr:#010x} off {off:#09x} size {size:#09x} ent {entsize}")
    print(f"   ELF file extent ~ {max(end, e_shoff + e_shnum * 40):#x} -> ends at file offset {base + max(end, e_shoff + e_shnum * 40):#x}")
