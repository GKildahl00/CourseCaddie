"""Browser regression checks. Run with Python and an installed Chrome/Chromium.

Optional: --browser PATH --screenshot PATH --viewport 390,844
GPS is simulated; no location permission or network connection is required.
"""

import argparse
import html
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile


CHECKS = r"""
<script>
window.addEventListener('load', async function () {
    const passed = [];
    const check = (condition, name) => {
        if (!condition) throw new Error(name);
        passed.push(name);
    };
    const byId = id => document.getElementById(id);
    const readings = () => [...document.querySelectorAll('#extraDistancesList dd')]
        .map(node => node.textContent.trim());
    const fix = (lat, lon) => ({timestamp: Date.now(), coords: {
        latitude: lat, longitude: lon, accuracy: 5
    }});
    let report;
    try {
        let success, failure, watches = 0, clears = 0;
        Object.defineProperty(navigator, 'geolocation', {configurable: true, value: {
            watchPosition(onSuccess, onFailure) {
                success = onSuccess;
                failure = onFailure;
                return ++watches;
            },
            clearWatch() { clears++; }
        }});
        // These unrelated device/network features are outside this regression.
        startCompass = function () {};
        stopCompass = function () {};
        maybeUpdateWind = function () {};
        byId('splashScreen').style.display = 'none';

        byId('romoCourseButton').click();
        byId('holeMap').click();
        check(imageViewer.classList.contains('open'), 'Picture opens fullscreen');
        check(!extraDistancesButton.hidden, 'Romo hole 1 offers extra distances');
        extraDistancesButton.click();
        check(extraDistancesDialog.open, 'Button opens modal');
        check(readings().length === 2 && readings().every(v => v === '— m'),
            'No invented distances before a GPS fix');
        check(!extraDistancesGps.hidden, 'GPS can be started inside the panel');
        check(byId('extraDistancesClose') === document.activeElement, 'Dialog receives focus');

        const targets = courses.romo9.holes[0].extraMeasurements;
        const expected = [
            [55 + 4/60 + 56.65/3600, 8 + 33/60 + 17.26/3600],
            [55 + 4/60 + 56.63/3600, 8 + 33/60 + 17.42/3600]
        ];
        check(targets.every((t, i) => Math.abs(t.lat - expected[i][0]) < 1e-9 &&
            Math.abs(t.lon - expected[i][1]) < 1e-9), 'Both DMS coordinates converted correctly');

        extraDistancesGps.click();
        check(watches === 1 && extraDistancesStatus.textContent.includes('Finding'),
            'Starting GPS shows waiting state');
        check(extraDistancesGps.hidden, 'Waiting does not start duplicate GPS watches');
        success(fix(...expected[0]));
        check(JSON.stringify(readings()) === JSON.stringify(['0 m', '3 m']),
            'Standing at short side measures zero and 3 metres to long side');
        check(extraDistancesStatus.textContent.includes('±5 m'), 'GPS accuracy displayed');
        success(fix(...expected[1]));
        check(JSON.stringify(readings()) === JSON.stringify(['3 m', '0 m']),
            'Moving to long side updates both readings without relabelling targets');
        check(/^\d+$/.test(byId('centerDistance').textContent),
            'Existing green distances still update');

        failure({code: 1, message: 'Permission denied'});
        check(readings().every(v => v === '— m') && !extraDistancesGps.hidden &&
            extraDistancesStatus.textContent.includes('Permission denied'),
            'GPS errors remove old readings and show retry');
        extraDistancesGps.click();
        check(watches === 2 && clears === 1, 'Retry replaces the failed GPS watch');
        success(fix(...expected[0]));
        check(readings()[0] === '0 m', 'Readings recover after GPS retry');

        document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true}));
        check(!extraDistancesDialog.open && imageViewer.classList.contains('open'),
            'Escape closes the panel while keeping the picture open');
        extraDistancesButton.click();
        check(readings()[0] === '0 m', 'Reopening uses the latest GPS position');
        byId('extraDistancesClose').click();
        check(!extraDistancesDialog.open && imageViewer.classList.contains('open'),
            'Panel close button keeps the picture open');
        extraDistancesButton.click();
        stopGPS();
        check(readings().every(v => v === '— m') && !extraDistancesGps.hidden,
            'Stopping GPS clears extra distances');

        byId('nextHoleButton').click();
        check(!extraDistancesDialog.open && !imageViewer.classList.contains('open'),
            'Changing holes dismisses the old measurements and picture');
        byId('holeMap').click();
        check(extraDistancesButton.hidden, 'Romo hole 2 has no extra-distances button');
        openCourse('sega');
        byId('holeMap').click();
        check(extraDistancesButton.hidden, 'Other courses do not inherit Romo targets');

        openCourse('romo9');
        byId('holeMap').click();
        extraDistancesButton.click();
        Object.defineProperty(navigator, 'geolocation', {configurable: true, value: undefined});
        extraDistancesGps.click();
        check(extraDistancesStatus.textContent.includes('does not support GPS') &&
            readings().every(v => v === '— m'), 'Unsupported GPS shows a useful message');

        // Leave the complete panel visible for the optional screenshot.
        positionUpdated(fix(55.08250, 8.55300));
        await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
        const rect = extraDistancesDialog.getBoundingClientRect();
        check(rect.left >= 0 && rect.right <= innerWidth && rect.top >= 0 && rect.bottom <= innerHeight,
            'Panel fits inside the viewport');
        check(extraDistancesDialog.scrollWidth <= extraDistancesDialog.clientWidth,
            'Panel content does not overflow horizontally');
        check(window.testRuntimeErrors.length === 0, 'No uncaught browser errors');
        report = {passed};
    } catch (error) {
        report = {passed, failure: error.stack};
    }
    const result = document.createElement('pre');
    result.id = 'test-report';
    result.hidden = true;
    result.textContent = JSON.stringify(report);
    document.body.append(result);
    if (window.parent !== window) window.parent.postMessage(report, '*');
});
</script>
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--browser')
    parser.add_argument('--screenshot')
    parser.add_argument('--viewport', default='390,844')
    args = parser.parse_args()
    browser = args.browser or shutil.which('chromium') or shutil.which('google-chrome')
    if not browser:
        browser = str(Path(os.environ.get('PROGRAMFILES', 'C:/Program Files')) /
                      'Google/Chrome/Application/chrome.exe')
    root = Path(__file__).resolve().parents[1]
    source = (root / 'index.html').read_text(encoding='utf-8')
    bootstrap = ('<base href="' + root.as_uri() + '/">'
                 '<script>window.testRuntimeErrors=[];'
                 'window.addEventListener("error",e=>testRuntimeErrors.push(e.message));</script>')
    source = source.replace('<head>', '<head>' + bootstrap, 1)
    source = source.replace('</body>', CHECKS + '</body>', 1)
    with tempfile.TemporaryDirectory(prefix='coursecaddie-tests-') as temp:
        page = Path(temp) / 'extra-distances.html'
        page.write_text(source, encoding='utf-8')
        # Chrome on Windows can enforce a minimum window width. An iframe gives
        # the app the requested viewport even when the host window is wider.
        width, height = (int(value) for value in args.viewport.split(','))
        wrapper = Path(temp) / 'browser.html'
        wrapper.write_text(
            '<!doctype html><html><head><meta charset="utf-8"></head><body style="margin:0">'
            '<iframe style="position:absolute;left:0;top:0;border:0;width:' + str(width) +
            'px;height:' + str(height) + 'px" src="' + page.as_uri() + '"></iframe>'
            '<script>window.addEventListener("message", function(event) {'
            'const report = document.createElement("pre"); report.id="test-report";'
            'report.hidden=true; report.textContent=JSON.stringify(event.data);'
            'document.body.append(report);});</script></body></html>', encoding='utf-8')
        command = [browser, '--headless=new', '--disable-gpu', '--no-first-run',
                   '--disable-background-networking', '--disable-component-update',
                   '--no-default-browser-check', '--force-device-scale-factor=1',
                   '--window-size=' + args.viewport, '--virtual-time-budget=5000',
                   '--user-data-dir=' + str(Path(temp) / 'profile'), '--dump-dom']
        if args.screenshot:
            command.append('--screenshot=' + str(Path(args.screenshot).resolve()))
        result = subprocess.run(command + [wrapper.as_uri()], capture_output=True,
                                encoding='utf-8', errors='replace', timeout=45)
        match = re.search(r'<pre id="test-report"[^>]*>(.*?)</pre>', result.stdout, re.S)
        if not match:
            raise SystemExit('No browser test report.\n' + result.stderr[-3000:])
        report = json.loads(html.unescape(match.group(1)))
        for check in report['passed']:
            print('PASS: ' + check)
        if 'failure' in report:
            raise SystemExit(report['failure'])
        print(str(len(report['passed'])) + ' browser checks passed.')


if __name__ == '__main__':
    main()
