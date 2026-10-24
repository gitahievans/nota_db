"""Read-only installed OSMD 1.9.0 source-model join, in local headless Chrome.

No npm install, frontend edit, external service, SVG/pixel mapping or MIDI claim.
Exit 2 means UNVERIFIED. Serves only explicit in-memory resources on loopback.
"""
import json
from pathlib import Path
import subprocess
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from html import unescape
import re

from files.musical_identity import index_musicxml
from files.reliability.references import REFERENCES, ROOT


HTML = '''<!doctype html><div id="score"></div><pre id="result">PENDING</pre>
<script src="/osmd.js"></script><script>
(async () => {
 try {
  const cases = await (await fetch('/cases')).json();
  const results = [];
  for (const c of cases) {
   const osmd = new opensheetmusicdisplay.OpenSheetMusicDisplay(document.getElementById('score'));
   await osmd.load(c.xml);
   const notes = [];
   for (const m of osmd.Sheet.SourceMeasures)
    for (const vc of m.VerticalSourceStaffEntryContainers)
     for (const se of vc.StaffEntries) {
      if (!se) continue;
      for (const ve of se.VoiceEntries)
       for (const n of ve.Notes) notes.push({
        measure: m.measureListIndex,
        part: osmd.Sheet.Instruments.indexOf(se.ParentStaff.ParentInstrument),
        staff: se.ParentStaff.Id, voice: ve.ParentVoice.VoiceId,
        onset: ve.Timestamp.RealValue * 4, duration: n.Length.RealValue * 4,
        rest: n.isRest(), step: n.Pitch ? n.Pitch.FundamentalNote : null,
        octave: n.Pitch ? n.Pitch.Octave + 3 : null,
        alter: n.Pitch ? n.Pitch.AccidentalHalfTones : null
       });
     }
   const used = new Set();
   for (const e of c.events) {
    const matches = notes.map((n,i) => ({n,i})).filter(({n,i}) =>
     !used.has(i) && n.measure === e.xml.measure && n.part === e.xml.part &&
     String(n.staff) === e.staff && String(n.voice) === e.voice &&
     Math.abs(n.onset - fraction(e.measure_onset)) < 1e-8 &&
     Math.abs(n.duration - fraction(e.duration)) < 1e-8 &&
     n.rest === (e.kind === 'rest') && (!e.written_pitch ||
      (n.step === {C:0,D:2,E:4,F:5,G:7,A:9,B:11}[e.written_pitch.step] &&
       n.octave === e.written_pitch.octave && n.alter === Number(e.written_pitch.alter))));
    if (matches.length !== 1) throw new Error(c.name + ':' + e.id + ' candidates=' + matches.length + ' notes=' + JSON.stringify(notes));
    used.add(matches[0].i);
   }
   if (used.size !== notes.length) throw new Error('Unmapped OSMD notes: ' + c.name);
   results.push({name:c.name, mapped:used.size});
  }
  document.getElementById('result').textContent = JSON.stringify({status:'PASS',results});
 } catch(e) { document.getElementById('result').textContent = JSON.stringify({status:'FAIL',error:String(e)}); }
})();
function fraction(s) { const a=s.split('/').map(Number); return a[0]/(a[1] || 1); }
</script>'''


def main():
    package = ROOT.parent / 'scoreanalyzr/node_modules/opensheetmusicdisplay'
    chrome = Path('C:/Program Files/Google/Chrome/Application/chrome.exe')
    if not chrome.exists() or not (package / 'package.json').exists():
        print('UNVERIFIED: installed OSMD and local Chrome required')
        return 2
    if json.loads((package / 'package.json').read_text())['version'] != '1.9.0':
        print('UNVERIFIED: requires OSMD exactly 1.9.0')
        return 2
    cases = []
    for name in ('melody', 'parts', 'rhythm', 'expression', 'harmony', 'distributed'):
        data = (REFERENCES / f'{name}.musicxml').read_bytes()
        cases.append({'name': name, 'xml': data.decode(), 'events': index_musicxml(data)['events']})
    # Hand-read supplement: three thirds over an independent quarter, then
    # another identically labelled bar. C4 is written, Bb3 sounds on a Bb instrument.
    opening = '<?xml version="1.0"?><score-partwise version="4.0"><part-list><score-part id="P1"><part-name>Bb</part-name></score-part></part-list><part id="P1">'
    attributes = '<attributes><divisions>3</divisions><time><beats>1</beats><beat-type>4</beat-type></time><transpose><diatonic>-1</diatonic><chromatic>-2</chromatic></transpose><clef><sign>G</sign><line>2</line></clef></attributes>'
    triplets = ''.join('<note><pitch><step>' + step + '</step><octave>4</octave></pitch><duration>1</duration><voice>1</voice><type>eighth</type><time-modification><actual-notes>3</actual-notes><normal-notes>2</normal-notes></time-modification></note>' for step in 'CDE')
    source = opening + '<measure number="A">' + attributes + triplets + '<backup><duration>3</duration></backup><note><pitch><step>C</step><octave>4</octave></pitch><duration>3</duration><voice>2</voice><type>quarter</type></note></measure><measure number="A"><note><rest/><duration>3</duration><voice>1</voice><type>quarter</type></note></measure></part></score-partwise>'
    cases.append({'name': 'triplets-voices-labels-transpose', 'xml': source,
                  'events': index_musicxml(source.encode())['events']})
    source = opening + '<measure number="1"><attributes><divisions>1</divisions><staves>2</staves><time><beats>4</beats><beat-type>4</beat-type></time><clef number="1"><sign>G</sign><line>2</line></clef><clef number="2"><sign>F</sign><line>4</line></clef></attributes><note><pitch><step>C</step><octave>4</octave></pitch><duration>4</duration><voice>1</voice><type>whole</type><staff>1</staff></note><backup><duration>4</duration></backup><note><pitch><step>C</step><octave>3</octave></pitch><duration>4</duration><voice>2</voice><type>whole</type><staff>2</staff></note></measure></part></score-partwise>'
    cases.append({'name': 'grand-staff', 'xml': source,
                  'events': index_musicxml(source.encode())['events']})
    resources = {'/': ('text/html', HTML.encode()), '/cases': ('application/json', json.dumps(cases).encode()),
                 '/osmd.js': ('text/javascript', (package / 'build/opensheetmusicdisplay.min.js').read_bytes())}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path not in resources:
                self.send_error(404)
                return
            kind, body = resources[self.path]
            self.send_response(200)
            self.send_header('Content-Type', kind)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with tempfile.TemporaryDirectory(prefix='nota-osmd-') as profile:
            result = subprocess.run([str(chrome), '--headless', '--disable-gpu', '--no-first-run',
                '--no-default-browser-check', f'--user-data-dir={profile}', '--dump-dom',
                '--virtual-time-budget=15000', f'http://127.0.0.1:{server.server_port}/'],
                capture_output=True, text=True, timeout=45)
        match = re.search(r'<pre id="result">(.*?)</pre>', result.stdout, re.S)
        if not match or match[1] == 'PENDING':
            print('UNVERIFIED: Chrome did not produce model results; exit', result.returncode)
            print(result.stderr[-1500:])
            return 2
        report = json.loads(unescape(match[1]))
        print(json.dumps(report, indent=2))
        return 0 if report['status'] == 'PASS' else 1
    except (OSError, subprocess.TimeoutExpired) as exc:
        print('UNVERIFIED:', str(exc))
        return 2
    finally:
        server.shutdown()
        server.server_close()


if __name__ == '__main__':
    raise SystemExit(main())
