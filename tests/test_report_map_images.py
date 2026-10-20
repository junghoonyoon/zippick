import sys
import re
import shutil
import subprocess
import unittest
from email.message import Message
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pipeline"))
import report_map_images


class ReportMapImagesTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node.js required")
    def test_pdf_preserves_available_tiles_and_continues_when_maps_are_incomplete(self):
        html = (Path(__file__).resolve().parents[1] / "앱화면/real-estate-search.html").read_text()
        helper = re.search(r"    async function preparePdfReportMaps\(root\) \{.*?\n    \}", html, re.S).group()
        script = helper + r'''
const assert = require('node:assert/strict');
const location = {href:'https://example.test/'};
const tile = 'http://mts.kakaocdn.net/api/v1/tile/tiles/1.png';
const elements = [0,1].map(() => ({tagName:'IMG',currentSrc:tile,src:tile,style:{},
  removeAttribute(name) { if(name === 'src') this.src = ''; },
  async decode() { assert.equal(this.src,'data:image/png;base64,dGlsZQ=='); }
}));
elements.push({tagName:'DIV',style:{},background:`url("${tile}")`});
const map = {dataset:{},querySelectorAll:() => elements};
const root = {querySelectorAll:() => [map]};
async function mountZippickReportMap() {
  assert.fail('PDF 저장 중 지도를 다시 불러오면 안 된다');
}
const getComputedStyle = element => ({backgroundImage:element.background || 'none'});
class FileReader {
  readAsDataURL() { this.result='data:image/png;base64,dGlsZQ==';this.onload(); }
}
let calls=0;
let fetch = async url => {
  assert.notEqual(map.dataset.zprMapState,'ready');
  assert.equal(url,`/api/report-map-image?url=${encodeURIComponent(tile)}`);
  calls++; return {ok:true,blob:async()=>({})};
};
(async()=>{
  await preparePdfReportMaps(root);
  assert.equal(calls,1,'같은 타일은 한 번만 읽어야 한다');
  assert.equal(elements[2].style.backgroundImage,'url("data:image/png;base64,dGlsZQ==")');
  for (const state of ['loading', 'error', 'empty', undefined]) {
    map.dataset.zprMapState = state;
    elements.forEach(element => { if(element.tagName === 'IMG') element.src = tile; });
    fetch = async()=>({ok:false});
    await preparePdfReportMaps(root);
    assert.equal(elements[0].style.visibility,'hidden');
    assert.equal(elements[0].src,'');
    assert.equal(elements[2].style.backgroundImage,'none');
  }
  fetch = async()=>{ throw new Error('network failure'); };
  await preparePdfReportMaps(root);
  fetch = async()=>({ok:true,blob:async()=>({})});
  elements[0].decode = async()=>{ throw new Error('broken tile'); };
  await preparePdfReportMaps(root);
  assert.equal(elements[0].style.visibility,'hidden');
})().catch(error=>{console.error(error);process.exit(1)});
'''
        result = subprocess.run(["node"], input=script, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_only_map_images_can_be_requested(self):
        invalid = [
            "https://127.0.0.1/private.png", "file:///etc/passwd",
            "https://mts.kakaocdn.net.evil.test/api/v1/tile/a.png",
            "https://user@mts.kakaocdn.net/api/v1/tile/a.png",
            "https://mts.kakaocdn.net:443/api/v1/tile/a.png",
            "https://mts.kakaocdn.net/api/v1/tile/../private.png",
            "https://mts.kakaocdn.net/api/v1/tile/%2e%2e/private.png",
            "https://mts.kakaocdn.net/api/v1/tile/a.svg",
            "https://t1.kakaocdn.net/other/a.png",
            "https://mts.kakaocdn.net/api/v1/tile/a.png?url=http://localhost",
        ]
        with patch.object(report_map_images, "build_opener") as opener:
            for url in invalid:
                with self.subTest(url=url), self.assertRaises(ValueError):
                    report_map_images.fetch_image(url)
            opener.assert_not_called()

    def test_tile_is_loaded_over_https_without_redirects(self):
        response = MagicMock()
        response.headers = Message()
        response.headers["Content-Type"] = "image/png"
        response.read.return_value = b"image-bytes"
        opener = MagicMock()
        opener.open.return_value.__enter__.return_value = response
        with patch.object(report_map_images, "build_opener", return_value=opener) as build:
            self.assertEqual(report_map_images.fetch_image(
                "http://mts.kakaocdn.net/api/v1/tile/PNGSD02/v26/4/994/455.png"
            ), (b"image-bytes", "image/png"))
        self.assertIsInstance(build.call_args.args[0], report_map_images.NoRedirect)
        self.assertEqual(opener.open.call_args.args[0].full_url,
                         "https://mts.kakaocdn.net/api/v1/tile/PNGSD02/v26/4/994/455.png")
        self.assertEqual(opener.open.call_args.kwargs["timeout"], 10)

    def test_html_and_oversized_responses_are_rejected(self):
        for mime, body in [("text/html", b"<html>"),
                           ("image/png", b"x" * (report_map_images.MAX_IMAGE_BYTES + 1)),
                           ("image/png", b"")]:
            with self.subTest(mime=mime, size=len(body)):
                response = MagicMock()
                response.headers = Message()
                response.headers["Content-Type"] = mime
                response.read.return_value = body
                opener = MagicMock()
                opener.open.return_value.__enter__.return_value = response
                with patch.object(report_map_images, "build_opener", return_value=opener):
                    with self.assertRaises(ValueError):
                        report_map_images.fetch_image("https://tile.openstreetmap.org/1/1/1.png")


if __name__ == "__main__":
    unittest.main()
