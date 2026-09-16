import re, json

def sel(html, name):
    m = re.search(r'<select name="%s".*?</select>' % name, html, re.S)
    return m.group(0) if m else ""

for f in ("temp_rendered.html", "temp_rendered_all.html"):
    html = open(f, encoding="utf-8").read()
    print("=== " + f)
    month = sel(html, "month")
    year = sel(html, "year")
    comp = sel(html, "company_id")
    print("month=6 selected:", 'value="6" class="month-option" selected' in month)
    print("year=2026 selected:", re.search(r'<option value="2026".*?selected', year, re.S) is not None)
    print("company selected opts:", re.findall(r'<option value="(\d+)" selected>', comp))
    print("active tab-panes:", re.findall(r'<div[^>]*class="tab-pane[^"]*active[^"]*"', html))
    print("active reports-tabs:", re.findall(r'class="[^"]*tab-link[^"]*active[^"]*"', html))
    pl = re.search(r"plChart\b.*", html, re.S)
    if pl:
        print("plChart data:", re.findall(r"data:\s*(\[[^\]]*\])", pl.group(0)))
    print()