"""Draw the last year of GitHub contributions as a pinned cloth.

Each week is a column of the cloth and each day a row. A day's contribution
count hangs a small weight on that vertex, so busy weeks pull the fabric down
and colour it. The cloth is pinned along the top edge, like the PBD cloth on
the portfolio hero.

Runs in GitHub Actions with only the Python standard library:
    GITHUB_TOKEN=... python contribution_cloth.py soz1p assets/
Without a token (or with --empty) it draws an empty cloth.
"""
import datetime as dt
import json
import math
import os
import sys
import urllib.request

ACC = '#f2551d'
RAMP = {'light': ['#f1f2f5', '#dcd8f2', '#b9a8e3', '#e48aa8', '#f2551d'],   # none, low .. high: wisteria to pink to orange
        'dark': ['#262b33', '#3d3760', '#62519e', '#c0628a', '#f2551d']}
BLOBS = ['#4fb3c4', '#f6a04a', '#e8a0b8', '#8b81c3']
THEMES = {
    'light': dict(bg='#ffffff', ink='#15181b', ink2='#4b535b', ink3='#8b9299', line='#cdd2d7',
                  mesh='rgba(21,24,27,.09)', blob=.5, zero='#f1f2f5', shade_dark=.10),
    'dark': dict(bg='#0f1216', ink='#f3f5f7', ink2='#b7bec6', ink3='#7d8690', line='#3a4148',
                 mesh='rgba(15,18,22,.35)', blob=.30, zero='#2a3038', shade_dark=.18),
}

QUERY = """query($login:String!){user(login:$login){contributionsCollection{contributionCalendar{
totalContributions weeks{contributionDays{date contributionCount weekday}}}}}}"""


def fetch(login, token):
    req = urllib.request.Request(
        'https://api.github.com/graphql',
        data=json.dumps({'query': QUERY, 'variables': {'login': login}}).encode(),
        headers={'Authorization': f'bearer {token}', 'Content-Type': 'application/json',
                 'User-Agent': 'contribution-cloth'})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.load(r)
    if 'errors' in data:
        raise RuntimeError(f'GraphQL error: {data["errors"]}')
    cal = data['data']['user']['contributionsCollection']['contributionCalendar']
    weeks = [[(d['date'], d['contributionCount'], d['weekday']) for d in w['contributionDays']] for w in cal['weeks']]
    return cal['totalContributions'], weeks


def scrape(login):
    """Read the public contribution calendar page (what any visitor sees,
    including private-contribution counts when the profile shows them)."""
    import re
    req = urllib.request.Request(f'https://github.com/users/{login}/contributions',
                                 headers={'User-Agent': 'contribution-cloth'})
    with urllib.request.urlopen(req, timeout=30) as r:
        html = r.read().decode('utf-8', 'replace')
    dates = dict(re.findall(r'data-date="(\d{4}-\d\d-\d\d)"[^>]*?id="([^"]+)"', html))
    dates.update({d: i for i, d in re.findall(r'id="([^"]+)"[^>]*?data-date="(\d{4}-\d\d-\d\d)"', html)})
    counts = {}
    for cid, txt in re.findall(r'<tool-tip[^>]*for="([^"]+)"[^>]*>([^<]*)</tool-tip>', html):
        m = re.match(r'\s*(\d+|No) contribution', txt)
        if m:
            counts[cid] = 0 if m.group(1) == 'No' else int(m.group(1))
    days = sorted((d, counts.get(cid, 0)) for d, cid in dates.items())
    if not days:
        return None
    weeks, cur = [], []
    for d, c in days:
        wd = (dt.date.fromisoformat(d).weekday() + 1) % 7
        if wd == 0 and cur:
            weeks.append(cur); cur = []
        cur.append((d, c, wd))
    if cur:
        weeks.append(cur)
    return sum(c for _, c in days), weeks


def empty_weeks():
    today = dt.date.today()
    start = today - dt.timedelta(days=364 + (today.weekday() + 1) % 7)
    weeks, d = [], start
    while d <= today:
        w = []
        for _ in range(7):
            if d <= today:
                w.append((d.isoformat(), 0, (d.weekday() + 1) % 7))
            d += dt.timedelta(days=1)
        weeks.append(w)
    return 0, weeks



def public_commits(login, token):
    """Count unique commits authored by login in the eight public portfolio repositories.
    Fail closed on API errors rather than publishing a misleading empty calendar.
    """
    from urllib.parse import urlencode, quote
    from collections import Counter
    today = dt.datetime.now(dt.timezone.utc).date()
    start = today - dt.timedelta(days=364)
    names = [login, 'jeon-sojin-portfolio', 'STC-Showcase', 'VDR-Showcase',
             'NeuralDynaRender-Showcase', 'QtGTCG-Showcase',
             'Edge-of-Survival-Showcase', 'Fire-Evacuation-Showcase']
    headers = {'Accept': 'application/vnd.github+json',
               'User-Agent': 'contribution-cloth',
               'X-GitHub-Api-Version': '2022-11-28'}
    if token:
        headers['Authorization'] = f'Bearer {token}'
    seen, counts = set(), Counter()
    for name in names:
        base = f'https://api.github.com/repos/{quote(login, safe="")}/{quote(name, safe="")}'
        # Never aggregate commits from a repository that has become private.
        req = urllib.request.Request(base, headers=headers)
        with urllib.request.urlopen(req, timeout=45) as response:
            metadata = json.load(response)
        if metadata.get('visibility') != 'public':
            print(f'Skipping non-public repository: {name}')
            continue
        page = 1
        while True:
            params = urlencode({'author': login, 'since': start.isoformat() + 'T00:00:00Z',
                                'until': today.isoformat() + 'T23:59:59Z',
                                'per_page': 100, 'page': page})
            req = urllib.request.Request(base + '/commits?' + params, headers=headers)
            with urllib.request.urlopen(req, timeout=45) as response:
                batch = json.load(response)
            if not isinstance(batch, list):
                raise ValueError(f'Unexpected commit response for {name}')
            for commit in batch:
                sha = commit['sha']
                author = commit.get('author') or {}
                if author.get('login', '').lower() != login.lower() or sha in seen:
                    continue
                seen.add(sha)
                date = dt.datetime.fromisoformat(commit['commit']['author']['date'].replace('Z', '+00:00')).astimezone(dt.timezone.utc).date()
                if start <= date <= today:
                    counts[date] += 1
            if len(batch) < 100:
                break
            page += 1
    weeks, week = [], []
    day = start
    while day <= today:
        wd = (day.weekday() + 1) % 7
        if wd == 0 and week:
            weeks.append(week)
            week = []
        week.append((day.isoformat(), counts[day], wd))
        day += dt.timedelta(days=1)
    if week:
        weeks.append(week)
    return sum(counts.values()), weeks

def mix(a, b, t):
    a = [int(a[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(b[i:i + 2], 16) for i in (1, 3, 5)]
    return '#%02x%02x%02x' % tuple(round(x + (y - x) * t) for x, y in zip(a, b))


def level(c, q):
    if c <= 0:
        return 0
    for i, t in enumerate(q, 1):
        if c <= t:
            return i
    return 4


def draw(total, weeks, mode, login, source='calendar'):
    metric = 'public portfolio commits' if source == 'public' else 'GitHub contributions'
    source_note = 'Selected public repositories · default branches · UTC' if source == 'public' else 'GitHub contribution calendar'
    th = THEMES[mode]
    W, H = 1200, 330
    ncol = len(weeks)
    x0, x1, top = 60, 1140, 92

    # grid of counts (week, weekday); missing future days count as 0
    grid = [[0] * 7 for _ in range(ncol)]
    for i, w in enumerate(weeks):
        for date, c, wd in w:
            grid[i][wd] = c
    counts = sorted(c for col in grid for c in col if c > 0)
    if counts:
        q = [counts[int(len(counts) * f) - 1 if int(len(counts) * f) > 0 else 0] for f in (.25, .5, .75)]
    else:
        q = [1, 2, 3]
    mx = max(counts) if counts else 1

    # Vertices sit on the corners of the day cells: (ncol+1) x 8.
    # A cell's weight pulls the vertices at and below it, spreading a little sideways.
    def sag(i, j):
        s = 0.0
        for k in range(min(j, 7)):
            for di in (-2, -1, 0, 1):
                ii = i + di
                if 0 <= ii < ncol and grid[ii][k]:
                    s += math.log1p(grid[ii][k]) / math.log1p(mx) * (.25, .7, 1.0, .55)[di + 2]
        return s

    raw = [[sag(i, j) for j in range(8)] for i in range(ncol + 1)]
    peak = max(max(c) for c in raw) or 1
    rh = 20
    cw = (x1 - x0) / ncol

    def pt(i, j):
        drape = 3.0 * math.sin(i * .55) * (j / 7)
        y = top + j * rh + raw[i][j] / peak * 24 + drape + (j / 7) ** 2 * 6
        x = x0 + i * cw + math.sin(j * .9 + i * .3) * 1.1 * (j / 7)
        return x, y

    P = [[pt(i, j) for j in range(8)] for i in range(ncol + 1)]
    ramp = RAMP[mode]

    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" '
           f'aria-label="{total} {metric} by {login} in the last year, drawn as a pinned cloth">',
           '<defs>',
           f'<filter id="b" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="70"/></filter>',
           f'<clipPath id="c"><rect width="{W}" height="{H}" rx="22"/></clipPath>',
           '</defs>',
           f'<g clip-path="url(#c)"><rect width="{W}" height="{H}" fill="{th["bg"]}"/>',
           f'<g filter="url(#b)" opacity="{th["blob"]}">'
           f'<circle cx="120" cy="40" r="170" fill="{BLOBS[0]}"/><circle cx="560" cy="-10" r="150" fill="{BLOBS[1]}"/>'
           f'<circle cx="1100" cy="80" r="180" fill="{BLOBS[2]}"/><circle cx="760" cy="330" r="170" fill="{BLOBS[3]}"/></g>']

    out.append(f'<text x="{x0}" y="50" font-family="Archivo,Helvetica,Arial,sans-serif" font-size="22" font-weight="700" fill="{th["ink"]}">Contribution cloth</text>')
    out.append(f'<text x="{x1}" y="50" text-anchor="end" font-family="Archivo,Helvetica,Arial,sans-serif" font-size="14" fill="{th["ink2"]}">'
               + f'{total:,} {metric} in the last year' + '</text>')

    sway = ('<animateTransform attributeName="transform" type="skewX" values="0;.8;0;-.6;0" dur="10s" '
            'repeatCount="indefinite" calcMode="spline" keySplines=".45 0 .55 1;.45 0 .55 1;.45 0 .55 1;.45 0 .55 1"/>')
    out.append(f'<g transform="translate(0 {top})"><g>{sway}<g transform="translate(0 {-top})">')
    for j in range(7):
        for i in range(ncol):
            a, b, c, d = P[i][j], P[i + 1][j], P[i + 1][j + 1], P[i][j + 1]
            col = ramp[level(grid[i][j], q)]
            stretch = ((d[1] - a[1]) + (c[1] - b[1])) / 2 - rh     # stretched cells read as folds
            col = mix(col, '#000000', min(.3, max(0.0, stretch / 22) * th['shade_dark'] * 2.2))
            out.append(f'<path d="M{a[0]:.1f} {a[1]:.1f}L{b[0]:.1f} {b[1]:.1f}L{c[0]:.1f} {c[1]:.1f}L{d[0]:.1f} {d[1]:.1f}Z" '
                       f'fill="{col}" stroke="{th["mesh"]}" stroke-width=".7"/>')
    out.append('</g></g></g>')

    # rod and pins
    out.append(f'<path d="M{x0 - 18} {top}H{x1 + 18}" stroke="{th["ink"]}" stroke-width="1.6"/>')
    for i in range(0, ncol + 1, 4):
        out.append(f'<circle cx="{P[i][0][0]:.1f}" cy="{top}" r="3.6" fill="{ACC}"/>')

    # month labels
    last = None
    for i, w in enumerate(weeks):
        m = w[0][0][:7]
        if m != last and i < ncol - 2:
            name = dt.date.fromisoformat(w[0][0]).strftime('%b')
            out.append(f'<text x="{x0 + i * cw:.1f}" y="{H - 52}" font-family="Archivo,Helvetica,Arial,sans-serif" font-size="12" fill="{th["ink3"]}">{name}</text>')
            last = m

    # legend
    lx = x1 - 5 * 20 - 70
    out.append(f'<text x="{lx - 10}" y="{H - 24}" text-anchor="end" font-family="Archivo,Helvetica,Arial,sans-serif" font-size="12" fill="{th["ink3"]}">Less</text>')
    for k in range(5):
        out.append(f'<rect x="{lx + k * 20}" y="{H - 35}" width="14" height="14" rx="3" fill="{RAMP[mode][k]}" stroke="{th["mesh"]}"/>')
    out.append(f'<text x="{lx + 5 * 20 + 4}" y="{H - 24}" font-family="Archivo,Helvetica,Arial,sans-serif" font-size="12" fill="{th["ink3"]}">More</text>')
    out.append(f'<text x="{x0}" y="{H - 24}" font-family="Archivo,Helvetica,Arial,sans-serif" font-size="12" fill="{th["ink3"]}">'
               f'{source_note} · Updated {dt.datetime.now(dt.timezone.utc).date().isoformat()}.</text>')
    out.append('</g>')
    out.append(f'<rect x=".5" y=".5" width="{W - 1}" height="{H - 1}" rx="21.5" fill="none" stroke="{th["line"]}" stroke-opacity=".7"/>')
    out.append('</svg>')
    return '\n'.join(out)


def main():
    login = sys.argv[1] if len(sys.argv) > 1 else 'soz1p'
    outdir = sys.argv[2] if len(sys.argv) > 2 else 'assets'
    token = os.environ.get('GITHUB_TOKEN')
    source = 'calendar'
    if '--empty' in sys.argv:
        total, weeks = empty_weeks()
    else:
        total, weeks = 0, []
        if token:
            try:
                total, weeks = fetch(login, token)
            except Exception as e:
                print('GraphQL calendar unavailable:', e)
        if not total:
            # Hidden profile activity can return a successful but empty calendar.
            # Use verified public commit history rather than scraping hidden activity.
            total, weeks = public_commits(login, token)
            source = 'public'
    os.makedirs(outdir, exist_ok=True)
    for mode in THEMES:
        with open(os.path.join(outdir, f'contribution-cloth-{mode}.svg'), 'w') as f:
            f.write(draw(total, weeks, mode, login, source))
    print(f'{login}: {total} {source} events, {len(weeks)} weeks')


if __name__ == '__main__':
    main()
