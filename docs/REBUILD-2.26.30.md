# mDIR-U 2.26.30 개발·재빌드 안내

## 기준

mDIR-U 2.26.15 (`4083c174665e0b270700873a150571dfb3048325`)에 mDIR-P 2.26.30의 공통 개선을 Ubuntu 방식으로 반영했다. Windows 코드를 통째로 교체하지 않고 Linux의 경로, 휴지통, 실행 명령, 터미널 썸네일을 유지했다.

## 변경 사항과 소스

- `recent_folders.py`, `base.py`, `ui/dialogs.py`: 양쪽 경로 표시줄 ▼ 및 Alt+Down, 공유 최근 폴더 40개, 성공한 이동만 기록, 바깥 클릭 전달.
- `file_pane.py`: 여러 항목 선택을 묶어서 갱신하고 Shift 범위가 달라진 부분만 변경.
- `core.py`, `thumbnail_view.py`: 목록과 썸네일에서 30ms 단위 오른쪽 드래그 처리, 가장자리 거리별 자동 스크롤, 버튼 해제 시 마지막 위치 반영.
- `office_pdf_preview.py`, `preview/document.py`: LibreOffice로 Excel/Word/PowerPoint를 PDF로 변환한 후 재사용. 경로·크기·수정 시각으로 무효화, 900개/3GiB 제한, 45초 제한 시간, 변환 중 원본 변경 검사, 원자적 파일 교체. 각 작업은 별도 프로필과 프로세스 그룹을 사용하고 취소 시 해당 그룹만 종료한다. 잠금 대기 중 취소도 처리한다.
- `fast_app.py`: 지연된 시작 화면 처리가 열린 대화상자 포커스를 가져가지 않도록 한다.
- `app.py`: 선택 반전 버튼은 노랑/흰색 별표로 표시한다.

## 플랫폼 차이

| 기능 | Ubuntu 구현 |
|---|---|
| Office 미리보기 | LibreOffice PDF 변환. Microsoft Office COM은 사용하지 않음 |
| 썸네일 | 터미널 내부 그리드. Windows의 별도 네이티브 오버레이와 다름 |
| 파일 삭제 | 기존 Linux 휴지통 및 권한 오류 처리 유지. Windows UAC 관리자 재시도는 없음 |
| 터미널 | 기존 Linux 터미널 실행 방식 유지. Windows Terminal 프로필은 설치하지 않음 |
| 설정/캐시 | 기존 XDG 설정·상태 저장. Office 캐시는 XDG_CACHE_HOME/mdir-u/office-pdf-v1 |

LibreOffice가 없으면 기존 기본 문서 미리보기를 사용한다. LibreOffice 변환 실패/시간 초과는 오류로 표시한다. Ubuntu 원본 설치기는 LibreOffice 구성 요소를 설치하고 Debian 패키지는 권장 의존성으로 지정한다.

## 빌드 및 검사 (Ubuntu 24.04, Python 3.12)

```bash
sudo apt update
sudo apt install -y python3-venv xdg-utils poppler-utils nano libreoffice-calc libreoffice-writer libreoffice-impress
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[preview,dev]'
python -m mdir_u --check
python -m unittest discover -s tests -v
python -m build
bash packaging/debian/build_deb.sh
sudo apt install ./dist/mdir-u_2.26.30_amd64.deb
/opt/mdir-u/venv/bin/python -P -m mdir_u --check
python tools/package_release.py
```

소스 압축 도구는 Git HEAD를 사용한다. 전체 저장소를 복제하고 해당 릴리즈 태그를 체크아웃해야 한다. `.github/workflows/ci.yml`은 Ubuntu에서 전체 검사, 실제 LibreOffice Excel 변환, wheel 빌드, Debian 패키지 설치 및 설치본 자체 검사를 수행한다. main에 병합한 뒤 동일 절차가 통과하면 GitHub Release를 생성한다.

## 회귀 검사와 수동 확인

`test_release30.py`는 캐시 무효화/손상, 대기 중 취소, 실제 LibreOffice Excel PDF 변환 및 양쪽 메뉴·선택·바깥 클릭을 검사한다. `test_recent_folders.py`는 MRU 지속성을 검사한다. 기존 키보드·파일 작업·썸네일 테스트도 유지한다. LibreOffice가 없는 로컬 환경에서는 실제 변환 테스트가 건너뛰어지므로 LibreOffice를 설치한 Ubuntu CI 결과를 확인한다.

실제 Ubuntu 터미널의 배율, 마우스 보고 방식, 복잡한 Word/PowerPoint 레이아웃은 사용자 환경에서 추가 확인한다. 자동 검사가 모든 터미널과 문서의 화면 품질을 보장하지는 않는다. 동일 앱을 재현하려면 릴리즈 태그 전체 소스, 이 문서, pyproject.toml 및 설치 스크립트를 함께 보관한다.
