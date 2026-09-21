import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from mdir_u import office_pdf_preview as office
from mdir_u.app import MDirApp
from mdir_u.ui.dialogs import RecentFolderScreen


class OfficeCacheTests(unittest.TestCase):
    def test_cache_invalidation_and_corruption(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'XDG_CACHE_HOME': folder}):
            source = Path(folder) / 'sample.xlsx'; source.write_bytes(b'one')
            target = office.cache_path(source); target.parent.mkdir(parents=True)
            target.write_bytes(b'%PDF-1.4\n%%EOF\n')
            with patch.object(office, 'executable', side_effect=AssertionError('cache must avoid Office')):
                self.assertEqual(office.render_cached(source), target)
            source.write_bytes(b'longer version')
            self.assertNotEqual(office.cache_path(source), target)
            target.write_bytes(b'broken')
            self.assertFalse(office.valid_pdf(target))

    def test_waiting_request_is_cancelled_without_starting_process(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'XDG_CACHE_HOME': folder}), \
             patch.object(office, 'executable', return_value='libreoffice'), patch.object(office.subprocess, 'Popen') as popen:
            source = Path(folder) / 'queued.xlsx'; source.write_bytes(b'fixture')
            cancel = threading.Event(); errors = []
            def run():
                try: office.render_cached(source, cancel=cancel)
                except RuntimeError as exc: errors.append(str(exc))
            office._LOCK.acquire()
            worker = threading.Thread(target=run)
            try:
                worker.start(); cancel.set(); worker.join(2)
                self.assertFalse(worker.is_alive())
                self.assertEqual(errors, ['Preview cancelled'])
                popen.assert_not_called()
            finally:
                office._LOCK.release(); worker.join(2)

    @unittest.skipUnless(office.executable(), 'LibreOffice not installed')
    def test_real_libreoffice_excel_export_and_cache_reuse(self):
        from openpyxl import Workbook
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'XDG_CACHE_HOME': folder}):
            source = Path(folder) / 'worksheet.xlsx'
            book = Workbook(); book.active['A1'] = 'mDIR-U 2.26.30'; book.save(source); book.close()
            result = office.render_cached(source)
            self.assertTrue(office.valid_pdf(result))
            import fitz
            with fitz.open(result) as pdf:
                self.assertGreater(len(pdf), 0)
                self.assertIn('mDIR-U', pdf[0].get_text())
            with patch.object(office.subprocess, 'Popen', side_effect=AssertionError('cache hit')):
                self.assertEqual(office.render_cached(source), result)


class RecentPaneTests(unittest.IsolatedAsyncioTestCase):
    async def test_both_panes_history_clickthrough_and_bulk_selection(self):
        from textual.widgets import OptionList
        from mdir_u import core
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            for name in ['left', 'right', 'target']:
                (root/name).mkdir(); (root/name/'item.txt').write_text('data')
            with patch.dict(os.environ, {'LOCALAPPDATA': folder, 'XDG_STATE_HOME': folder, 'XDG_CACHE_HOME': folder}), \
                 patch.object(core, 'CONFIG_PATH', root/'config.json'):
                app = MDirApp(); app.left_start=root/'left'; app.right_start=root/'right'; app._save_paths=lambda:None
                async with app.run_test(size=(160, 40)) as pilot:
                    async def wait(predicate):
                        for _ in range(150):
                            if predicate(): return
                            await pilot.pause(0.02)
                        self.assertTrue(predicate())
                    await wait(lambda: app.left.initial_listing_complete and app.right.initial_listing_complete and not app.query('#startup_cover'))
                    for side in ['left','right']:
                        pane=getattr(app,side); other=getattr(app,'right' if side=='left' else 'left')
                        app.recent_folders=[str(root/'target')]
                        await pilot.click(f'#{side}_recent_folders')
                        await wait(lambda:isinstance(app.screen,RecentFolderScreen) and app.screen.query_one(OptionList).has_focus)
                        original=other.current_path
                        await pilot.press('enter')
                        await wait(lambda:pane.current_path==root/'target' and pane.initial_listing_complete)
                        self.assertEqual(other.current_path,original)
                        pane.set_bulk_selection('all'); self.assertEqual(pane.marked,{root/'target/item.txt'})
                        pane.set_bulk_selection('invert'); self.assertFalse(pane.marked)
                    app.recent_folders=[str(root/'left')]
                    await pilot.press('alt+down')
                    await wait(lambda:isinstance(app.screen,RecentFolderScreen))
                    button=app.query_one('#left_thumbnail'); region=button.region
                    await pilot.click(offset=(region.x+1,region.y))
                    await wait(lambda:len(app.screen_stack)==1 and app.thumbnail_modes['left'])
