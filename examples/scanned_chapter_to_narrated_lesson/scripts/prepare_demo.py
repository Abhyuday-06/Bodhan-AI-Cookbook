"""Fetch the two assignment chapters into the ignored inputs directory."""
from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory

import httpx

NCERT = "https://www.aspirationsinstitute.com/wp-content/uploads/2021/01/9-Maths-NCERT-Book-Lines-and-Angles.pdf"
SCERT = "https://scert.kerala.gov.in/wp-content/uploads/2018/04/8_m_maths_part1.pdf"


def download(url, path):
    if path.is_file():
        return
    with httpx.Client(follow_redirects=True, timeout=90) as client:
        resp = client.get(url)
        resp.raise_for_status()
        if not resp.content.startswith(b"%PDF-"):
            raise RuntimeError("demo download did not return a PDF")
        path.write_bytes(resp.content)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dest", type=Path, default=Path("inputs"))
    dest = p.parse_args().dest.resolve()
    dest.mkdir(parents=True, exist_ok=True)
    english, malayalam = dest / "lines-and-angles.pdf", dest / "equations-ml.pdf"
    download(NCERT, english)
    if not malayalam.is_file():
        with TemporaryDirectory(dir=dest) as tmp:
            work = Path(tmp)
            full = work / "scert.pdf"
            download(SCERT, full)
            subprocess.run(["pdfseparate", "-f", "33", "-l", "44", str(full), str(work / "p-%d.pdf")],
                           check=True, timeout=90)
            target = work / "equations-ml.pdf"
            subprocess.run(["pdfunite", *(str(work / f"p-{i}.pdf") for i in range(33, 45)), str(target)],
                           check=True, timeout=90)
            target.replace(malayalam)
    print(english, malayalam, sep="\n")


if __name__ == "__main__":
    main()
