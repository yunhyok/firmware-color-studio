import sys, re, collections, struct
data = open(sys.argv[1], "rb").read()
strings = [(m.start(), m.group().decode()) for m in re.finditer(rb"[\x20-\x7e]{5,}", data)]
def grep(rx, limit=40, lo=0, hi=len(data)):
    rx = re.compile(rx, re.I)
    hits = [(o, s) for o, s in strings if lo <= o < hi and rx.search(s)]
    print(f"--- /{rx.pattern}/ : {len(hits)} hits")
    for o, s in hits[:limit]: print(f"  {o:08x} {s[:110]}")
for rx in sys.argv[2:]:
    grep(rx)
