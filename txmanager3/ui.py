"""
PySide / PyQt ui code for the texture manager.
"""
# -----------------------------------------------------------------------------
#
# Copyright (c) 1986-2018 Pixar. All rights reserved.
#
# The information in this file (the "Software") is provided for the exclusive
# use of the software licensees of Pixar ("Licensees").  Licensees have the
# right to incorporate the Software into other products for use by other
# authorized software licensees of Pixar, without fee. Except as expressly
# permitted herein, the Software may not be disclosed to third parties, copied
# or duplicated in any form, in whole or in part, without the prior written
# permission of Pixar.
#
# The copyright notices in the Software and this entire statement, including the
# above license grant, this restriction and the following disclaimer, must be
# included in all copies of the Software, in whole or in part, and all permitted
# derivative works of the Software, unless such copies or derivative works are
# solely in the form of machine-executable object code generated by a source
# language processor.
#
# PIXAR DISCLAIMS ALL WARRANTIES WITH REGARD TO THIS SOFTWARE, INCLUDING ALL
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS. IN NO EVENT SHALL PIXAR BE
# LIABLE FOR ANY SPECIAL, INDIRECT OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES
# WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER IN AN ACTION
# OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT OF OR IN
# CONNECTION WITH THE USE OR PERFORMANCE OF THIS SOFTWARE.  IN NO CASE WILL
# PIXAR'S TOTAL LIABILITY FOR ALL DAMAGES ARISING OUT OF OR IN CONNECTION WITH
# THE USE OR PERFORMANCE OF THIS SOFTWARE EXCEED $50.
#
# Pixar
# 1200 Park Ave
# Emeryville CA 94608
#
# -----------------------------------------------------------------------------


# TODO: move ui vis test for updates.
# TODO: clean up un-used stuff


# pylint: disable=import-error,undefined-variable,wildcard-import,invalid-name
try:
    from PySide2.QtCore import *
    from PySide2.QtGui import *
    from PySide2.QtWidgets import *
    try:
        import shiboken2 as shbkn
    except ImportError:
        import PySide2.shiboken2 as shbkn
    __qt_version__ = 5
except ImportError:
    from PySide.QtCore import *
    from PySide.QtGui import *
    __qt_version__ = 4
    import shiboken as shbkn
from functools import partial
import glob
import os
import copy
import queue
import threading
import txmanager3 as txm
import txmanager3.core as txmc
import txmanager3.txparams as txmp


UI_THREAD_NAME = 'txmgr_ui'
QResource.registerResource(
    os.path.join(txm.module_path(), 'txmanager.rcc'))
HELP_URL = QUrl('https://rmanwiki.pixar.com/display/RFM22/Texture+Manager')
BUTTON_STYLE = """QPushButton:enabled {
     background-color: #1975B3;
}"""
CLGRP_STYLE = """
QGroupBox::indicator {
    width: 12px;
    height: 12px;
}
QGroupBox::indicator:unchecked {
    image: url(:rman_collapse_off.svg);
}
QGroupBox::indicator:checked {
    image: url(:rman_collapse_on.svg);
}
"""
PROGRESS_BAR_STYLE = """QProgressBar {
    border-radius: 2px;
    text-align: center;
    font-size: 9px;
    margin-top: 1px;
}
QProgressBar::chunk {
    background-color: #0070BF;
}"""
BUTTON_STYLE_NO_BG = """QPushButton {
     background-color: none;
     border: none;
     margin-left: 5px;
     margin-right: 5px;
}
QPushButton:checked {
    background-color: none;
    border: none;
}
"""
NW = '<div style=\"white-space: nowrap;\">'
TT_QUEUE_RUNNING = ('%s<div><b>Converting !</b></div><div style=\"white-space: nowrap;\">'
                    'Click to pause the conversion queue.</div></div>' % NW)
TT_QUEUE_PAUSED = ('%s<div><b>Paused !</b></div><div style=\"white-space:nowrap;\">'
                   'Click to restart the conversion queue.</div></div>' % NW)
TT_QUEUE_INFO = [TT_QUEUE_RUNNING, TT_QUEUE_PAUSED]
TT_HELP = ("%s<div>Open the <b>Texture Manager's documentation</b></div>"
           "<div>on renderman.pixar.com</div></div>" % NW)



def _is_valid(obj):
    if not shbkn.isValid(obj):
        txm.txm_log().warning('%r IS INVALID !!', obj)
        return False
    return True


class Icons(object):
    """
    Class preloading icons and returning a fully configured
    QIcon instance.
    """
    check = QIcon(':rman_flat_check.svg')
    missing = QIcon(':rman_flat_missingDark.svg')
    queued = QIcon(':rman_flat_refreshDark.svg')
    processing = QIcon(':rman_flat_refreshLight_0.svg')
    error = QIcon(':rman_flat_warning.svg')
    rlogo = QIcon(':R_LOGO.svg')
    input_missing = QIcon(':rman_flat_missingRed.svg')
    start_pause = QIcon(':rman_queue_on.svg')
    start_pause.addFile(':rman_queue_paused.svg', state=QIcon.On)

    def __getattribute__(self, attr):
        return getattr(self, attr, None)

STATUS = [Icons.missing,       # STATE_MISSING
          Icons.check,         # STATE_EXISTS
          Icons.check,         # STATE_IS_TEX
          Icons.queued,        # STATE_IN_QUEUE
          Icons.processing,    # STATE_PROCESSING
          Icons.error,         # STATE_ERROR
          Icons.queued,        # STATE_REPROCESS
          Icons.error,         # STATE_UNKNWON
          Icons.input_missing] # STATE_INPUT_MISSING

PROG = [QIcon(':rman_flat_refreshLight_0.svg'),
        QIcon(':rman_flat_refreshLight_1.svg'),
        QIcon(':rman_flat_refreshLight_2.svg'),
        QIcon(':rman_flat_refreshLight_3.svg'),
        QIcon(':rman_flat_refreshLight_4.svg'),
        QIcon(':rman_flat_refreshLight_5.svg'),
        QIcon(':rman_flat_refreshLight_6.svg'),
        QIcon(':rman_flat_refreshLight_7.svg'),
        QIcon(':rman_flat_refreshLight_8.svg'),
        QIcon(':rman_flat_refreshLight_9.svg'),
        QIcon(':rman_flat_refreshLight_10.svg')]


class SourceImageItem(QStandardItem):
    """
    Represents an item in the queue list.
    The objects keeps a reference to the TxFile instance it represents and
    handles icon changes reflecting state/progress.
    """

    def __init__(self, txfile, txmgr):
        self.txfile = txfile
        super(SourceImageItem, self).__init__(QIcon(STATUS[self.txfile.state]),
                                              self.txfile.input_image)
        self.log = txm.txm_log()
        self.txmgr = txmgr
        if txfile.source_is_tex() or (txfile.state == txm.STATE_INPUT_MISSING):
            self.setEnabled(False)
        self.processing = False
        self.numErrors = 0
        # progress
        self.pval = 0.0
        self.pmax = float(self.txfile.num_textures())
        self.pstep = 0.0
        if self.pmax > 0.0:
            self.pstep = 10.0 / self.pmax

        self.set_tooltip()


    def set_tooltip(self):
        """
        Set tooltip. Tool tip is set to include
        a list of .tex files and the nodes that used
        these files.
        """

        if self.txmgr is None:
            return

        if self.txfile.is_rtxplugin:
            self.setToolTip('rtx plugin')
            return

        self.setToolTip(self.txfile.tooltip())

    def set_status(self, state):
        """
        Modifies the visible status by updating the icon.
        NOTE: item.state, txfile.dirty and txfile.numDirtyFiles have already
              been updated by txmanager3.core.TxMake_Process.
        TODO: how do we reflect an error in an image sequence ?
        """

        if not self.processing:
            if state == txmc.STATE_PROCESSING:
                self.processing = True
                offset = self.txfile.num_textures() - self.txfile.num_dirty_files
                self.pval = float(offset) * self.pstep
                self.setIcon(PROG[int(self.pval)])
        else:
            if state in [txmc.STATE_EXISTS, txmc.STATE_ERROR]:
                self.pval += self.pstep
                if self.pval >= len(PROG):
                    self.log.debug('self.pval = %d -> %s',
                                   int(self.pval), self.txfile.input_image)
                    self.pval = len(PROG) - 1
                self.setIcon(PROG[int(self.pval)])
                if state == txmc.STATE_ERROR:
                    self.numErrors += 1

            if self.txfile.num_dirty_files <= 0:
                self.pval = 0.0
                self.processing = False
                self.setIcon(STATUS[state])

        self.log.debug('state = %s  dirtyFiles: %d  processing: %s  img: %r',
                       txmc.STATE_AS_STR[state], self.txfile.num_dirty_files,
                       self.processing,
                       os.path.basename(self.txfile.input_image))
        self.setToolTip(self.txfile.tooltip())


class QueueWidget(QTreeView):
    """
    A QTreeView widget to display the texture manager's files and their state.
    """

    def __init__(self, *args, **kwargs):
        super(QueueWidget, self).__init__(*args)
        self.setAlternatingRowColors(True)

        # set model data
        self.modeldata = QStandardItemModel(self.parentWidget())
        self.setModel(self.modeldata)
        self.headerHidden = False
        self.reset_data()
        self.log = txm.txm_log()
        self.txmanager = kwargs.get('txmanager', None)
        self.curSelectedRow = -1

        # right-click context menu
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.connect(self, SIGNAL("customContextMenuRequested(const QPoint &)"), self.openMenu)

    def model(self):
        """
        Return the model data used by the view.
        """
        return self.modeldata

    def reset_data(self):
        """
        Re-initialize the tree view.
        """
        self.modeldata.clear()
        self.root = self.modeldata.invisibleRootItem()
        self.header().model().setHorizontalHeaderLabels(['Source Image'])
        # make sure the horizontal scroll bar appears when needed.
        self.header().setStretchLastSection(False)
        self.header().setSectionResizeMode(QHeaderView.ResizeToContents)

    def update_list(self, tx_list, append=False):
        """
        Refresh the QTreeView.
        """
        self.log.debug(' |_ queue update: tx_list=%r, append=%r',
                       tx_list, append)
        if not append:
            self.reset_data()
            self.log.debug('   |_ clean model data')

        if not tx_list:
            return

        for tx in tx_list:
            if not _is_valid(tx):
                continue
            self.root.appendRow([SourceImageItem(tx, self.txmanager)])

    def update_file_status(self, txfile, state):
        """Update a file's status in the ui.

        Args:
        - txfile (TxFile): The TxFile instance for that file.
        - state (): the new state.

        Kwargs:
        - kwarg:  keyword_argument.
        """
        self.log.debug(' |_ txfile=%r, state=%r',
                       txfile.input_image, txmc.STATE_AS_STR[state])
        try:
            items = self.root.model().findItems(txfile.input_image)
        except RuntimeError:
            # some widget may have been cleaned up by the time this function is
            # called from a thread.
            items = None
        except Exception as err:
            self.log.warning('Unexpected thingy: %s', err)
        else:
            if items and len(items) > 0:
                try:
                    items[0].set_status(state)
                except AttributeError as err:
                    self.log.debug('Soft fail: %s', err)
                self.scrollTo(
                    self.root.model().indexFromItem(items[0]),
                    hint=QTreeView.EnsureVisible)

    def update_line(self, index, state):
        """Just a manual debugging proc"""
        item = self.root.child(index, 0)
        item.set_status(state)

    def openMenu(self, point):
        """Create right click context menu."""
        selected = self.selectedIndexes()
        if not selected:
            return
        item = self.root.child(selected[0].row(), 0)
        if item is None or not item.isEnabled():
            return

        globalPos = self.mapToGlobal(point)
        menu = QMenu()
        clear_txt = "Re-convert:  %s" % os.path.basename(item.txfile.input_image)
        menu.addAction(clear_txt)
        qaction = menu.exec_(globalPos)

        if qaction:
            if qaction.text() == clear_txt:
                self.log.info('Reprocess Requested for: %r', item.txfile.input_image)
                item.txfile.delete_texture_files()
                self.txmanager.notify_host(item.txfile, force=True)
                self.txmanager.update_ui_list()
                self.txmanager.txmake_all(start_queue=self.txmanager.paused is False)


class EditedFile(object):
    """
    Represent the currently edited file, i.e. the file selected in the UI's
    list.
    """

    def __init__(self):
        self.dirty = False
        self.txfile = None
        self.params = None
        self.old_params = None
        self.log = txm.txm_log()

    def edit(self, txfile):
        """Resets the instance for editing.

        Args:
        - txfile (txmanager.txfile.TxFile): the instance corresponding to the
        selected file.
        """
        self.dirty = False
        self.txfile = txfile
        self.old_params = txfile.get_params()
        self.params = copy.copy(self.old_params)

    def set_param(self, name, value):
        """Set one of the file's params to a new value and updates the dirty
        based on its the original value.

        Args:
        - name (str): the parameter's name
        - value (any): the new value
        """
        if self.params is None:
            return
        setattr(self.params, name, value)
        self.dirty = self.params != self.old_params
        self.log.debug('edited file: %s = %s -> dirty = %s', name, value,
                      self.dirty)

    def override_params(self):
        """
        Pass the modified params to the texture manager and re-process the file.
        """
        if self.params is None:
            return
        self.txfile.set_params(self.params)
        self.txfile.re_process()



class TxManagerUI(QWidget):
    """
    Encapsulate the texture manager UI.
    """
    tx_diskspace_fmt = 'Texture Disk Space: %.2f %s'
    ui_file_update = Signal(tuple)

    def __init__(self, *args, **kwargs):
        super(TxManagerUI, self).__init__(*args)
        self.log = txm.txm_log()
        self.log.debug('TxManagerUI init')
        self.edited_file = EditedFile()

        # name the widget
        self.setObjectName('TxManagerUI_uniqueId')
        self.setWindowTitle('RenderMan Texture Manager')
        self.setMinimumSize(QSize(512, 256))

        # store known named args
        self.txmanager = kwargs.get('txmanager', None)
        self.parse_scene_func = kwargs.get('parse_scene_func', None)
        self.append_tx_func = kwargs.get('append_tx_func', None)
        self.help_func = kwargs.get('help_func', None)

        self.show_advanced = kwargs.get('show_advanced', False)
        self.adv_widgets = []

        # build ui
        self.build()
        # connect funcs to buttons
        self.setup(**kwargs)

        # ui threaded refresh
        self.refresh_queue = queue.Queue()
        self.num_tasks = 0
        self.ui_file_update.connect(self.update_file)

    def build(self):
        """Build the UI on instanciation"""
        # top layout
        #
        self.top_layout = QBoxLayout(QBoxLayout.TopToBottom, parent=self)

        # buttons in a horiz. box layout
        #
        but_lyt = QHBoxLayout(self.parentWidget())
        self.top_layout.addLayout(but_lyt)

        self.parse_scene_but = QPushButton("Parse Scene", self.parentWidget())
        self.parse_scene_but.setToolTip('Find all scene textures and add them '
                                        'to the queue.')
        but_lyt.addWidget(self.parse_scene_but)

        self.pick_image_but = QPushButton("Pick Images", self.parentWidget())
        self.pick_image_but.setToolTip('Add an image to the queue')
        but_lyt.addWidget(self.pick_image_but)

        self.pick_dir_but = QPushButton("Pick Directory", self.parentWidget())
        self.pick_dir_but.setToolTip('Add a directory of textures to the queue')
        but_lyt.addWidget(self.pick_dir_but)

        # main texture queue
        #
        self.queue_list = QueueWidget(self.parentWidget(), txmanager=self.txmanager)
        self.queue_list.clicked.connect(self.display_selection_settings)
        self.top_layout.addWidget(self.queue_list)

        # WIP
        self.tx_settings = QGroupBox('Settings', self.parentWidget())
        self.tx_settings.setCheckable(True)
        self.tx_settings.setChecked(True)
        self.tx_settings.setStyleSheet(BUTTON_STYLE + CLGRP_STYLE)
        self.tx_settings.toggled.connect(self.toggle_settings)
        self.top_layout.addWidget(self.tx_settings)

        # grid layout for the texture settings.
        #
        params_lyt = QGridLayout(self.parentWidget())
        params_lyt.setVerticalSpacing(4)
        self.tx_settings.setLayout(params_lyt)

        # texture type
        #
        tex_type_lbl = QLabel('Texture Type:  ', self.parentWidget())
        tex_type_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        params_lyt.addWidget(tex_type_lbl, 0, 0)

        self.tx_type = QComboBox(self.parentWidget())
        self.tx_type.addItem('Texture')
        self.tx_type.addItem('Environment Map')
        params_lyt.addWidget(self.tx_type, 0, 1)

        self.apply_but = QPushButton('Apply', self.parentWidget())
        self.apply_but.setToolTip('(Re) Convert the selected image with the '
                                  'current settings')
        params_lyt.addWidget(self.apply_but, 0, 3, Qt.AlignRight)

        # texture wrap modes
        #
        tex_mode_s_lbl = QLabel('ST Wrap Mode:  ', self.parentWidget())
        tex_mode_s_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        params_lyt.addWidget(tex_mode_s_lbl, 1, 0)

        self.tx_wrap_mode_s = QComboBox(self.parentWidget())
        self.tx_wrap_mode_s.addItem('Black')
        self.tx_wrap_mode_s.addItem('Clamp')
        self.tx_wrap_mode_s.addItem('Periodic')
        params_lyt.addWidget(self.tx_wrap_mode_s, 1, 1)

        self.tx_wrap_mode_t = QComboBox(self.parentWidget())
        self.tx_wrap_mode_t.addItem('Black')
        self.tx_wrap_mode_t.addItem('Clamp')
        self.tx_wrap_mode_t.addItem('Periodic')
        params_lyt.addWidget(self.tx_wrap_mode_t, 1, 2)

        # build advanced options
        self.build_advanced(params_lyt, 2)

        # clear cache, prefs and RenderMan button.
        #
        bottom_but_lyt = QGridLayout(self.parentWidget())
        bottom_but_lyt.setColumnStretch(0, 0)
        bottom_but_lyt.setColumnStretch(1, 1)
        bottom_but_lyt.setColumnStretch(2, 0)
        self.top_layout.addLayout(bottom_but_lyt)
        # help
        self.iconb = QPushButton(self.parentWidget())
        self.iconb.setIcon(Icons.rlogo)
        self.iconb.setToolTip(TT_HELP)
        bottom_but_lyt.addWidget(self.iconb, 0, 0, Qt.AlignLeft | Qt.AlignBottom)
        # disk space and progress bar
        info_lyt = QGridLayout(self.parentWidget())
        info_lyt.setColumnStretch(0, 0)
        info_lyt.setColumnStretch(1, 0)
        info_lyt.setHorizontalSpacing(0)
        bottom_but_lyt.addLayout(info_lyt, 0, 1, Qt.AlignCenter)
        # disk space
        self.tex_space = QLabel(self.tx_diskspace_fmt % (0, 'MB'), self.parentWidget())
        self.tex_space.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.tex_space.setAlignment(Qt.AlignCenter)
        self.tex_space.setStyleSheet('font-size: 10px')
        self.tex_space.setEnabled(False)
        info_lyt.addWidget(self.tex_space, 0, 0, Qt.AlignCenter | Qt.AlignBottom)
        # progress bar
        self.progress_bar = QProgressBar(self.parentWidget())
        self.progress_bar.setStyleSheet(PROGRESS_BAR_STYLE)
        self.progress_bar.setMinimumWidth(300)
        self.progress_bar.setFixedHeight(15)
        self.progress_bar.setFormat('%v of %m textures')
        self.progress_bar.setMinimum(0)
        info_lyt.addWidget(self.progress_bar, 1, 0, Qt.AlignCenter | Qt.AlignVCenter)
        # start/stop
        self.pause_but = QPushButton(self.parentWidget())
        self.pause_but.setCheckable(True)
        self.pause_but.setFlat(True)
        self.pause_but.setIcon(Icons.start_pause)
        self.pause_but.setStyleSheet(BUTTON_STYLE_NO_BG)
        self.set_queue_button_state(False, block_signals=True)
        info_lyt.addWidget(self.pause_but, 1, 1, Qt.AlignLeft | Qt.AlignVCenter)
        # clear
        self.clear_cache_but = QPushButton("Clear All Cache", self.parentWidget())
        self.clear_cache_but.setToolTip('Delete all converted textures')
        bottom_but_lyt.addWidget(self.clear_cache_but, 0, 2, Qt.AlignRight | Qt.AlignBottom)

        # set layout
        self.setLayout(self.top_layout)

    def build_advanced(self, params_lyt, row):
        """
        Build advanced section of UI
        """
        self.adv_lbl = QLabel('Advanced:  ', self.parentWidget())
        self.adv_lbl.setFixedHeight(20)
        self.adv_lbl.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        params_lyt.addWidget(self.adv_lbl, row, 0)
        self.adv_widgets.append(self.adv_lbl)

        self.tx_resize_lbl = QLabel('Resize:  ', self.parentWidget())
        self.tx_resize_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        params_lyt.addWidget(self.tx_resize_lbl, row + 1, 0)
        self.adv_widgets.append(self.tx_resize_lbl)

        self.tx_resize = QComboBox(self.parentWidget())
        for s in txmp.TX_RESIZES:
            self.tx_resize.addItem(s)
        params_lyt.addWidget(self.tx_resize, row + 1, 1)
        self.adv_widgets.append(self.tx_resize)

        self.tx_filter_lbl = QLabel('Filter:  ', self.parentWidget())
        self.tx_filter_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        params_lyt.addWidget(self.tx_filter_lbl, row + 2, 0)
        self.adv_widgets.append(self.tx_filter_lbl)

        self.tx_filter = QComboBox(self.parentWidget())
        for s in txmp.TX_FILTERS:
            self.tx_filter.addItem(s)
        params_lyt.addWidget(self.tx_filter, row + 2, 1)
        self.adv_widgets.append(self.tx_filter)

        self.tx_format_lbl = QLabel('Format:  ', self.parentWidget())
        self.tx_format_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        params_lyt.addWidget(self.tx_format_lbl, row + 4, 0)
        self.adv_widgets.append(self.tx_format_lbl)

        self.tx_format = QComboBox(self.parentWidget())
        for s in txmp.TX_FORMATS:
            self.tx_format.addItem(s)
        params_lyt.addWidget(self.tx_format, row + 4, 1)
        self.adv_widgets.append(self.tx_format)

        for w in self.adv_widgets:
            w.setVisible(self.show_advanced)
        self.tx_settings.adjustSize()

    def set_show_advanced(self, show_advanced):
        """
        Show advanced section or not.
        """
        self.show_advanced = show_advanced
        for w in self.adv_widgets:
            w.setVisible(self.show_advanced)
        self.toggle_settings(self.tx_settings.isChecked())

    def setup(self, **kwargs):
        """
        Connect buttons and widgets to user actions.
        """
        if self.parse_scene_func:
            self.parse_scene_but.clicked.connect(kwargs['parse_scene_func'])
        else:
            self.parse_scene_but.setEnabled(False)
        if self.append_tx_func:
            self.pick_image_but.clicked.connect(self.file_dialog)
            self.pick_dir_but.clicked.connect(
                partial(self.file_dialog, pick='dir'))
        else:
            self.pick_image_but.setEnabled(False)
            self.pick_dir_but.setEnabled(False)
        self.clear_cache_but.clicked.connect(self.clear_cache)
        if self.help_func:
            self.iconb.clicked.connect(
                partial(self.help_func, HELP_URL.toString()))
        self.pause_but.toggled.connect(self.toggle_queue)
        # params
        self.tx_type.activated.connect(
            partial(self.edit_param_value, 'texture_type'))
        self.tx_wrap_mode_s.activated.connect(
            partial(self.edit_param_value, 'smode'))
        self.tx_wrap_mode_t.activated.connect(
            partial(self.edit_param_value, 'tmode'))
        self.apply_but.clicked.connect(self.apply_edit)
        self.apply_but.setEnabled(False)

        # advanced params
        self.tx_resize.activated.connect(
            partial(self.edit_param_value, 'resize'))
        self.tx_filter.activated.connect(
            partial(self.edit_param_value, 'texture_filter'))
        self.tx_format.activated.connect(
            partial(self.edit_param_value, 'texture_format'))

    def file_dialog(self, pick='file'):
        """
        Opens a file dialog to pick a file or a directory. The images will be
        added to the active TxManager object.
        """
        if pick == 'file':
            ffilter = ('All Files (*.*);;OpenExr (*.exr);;HDR (*.hdr);;'
                       'TIFF (*.tif);;PNG (*.png)')
            fcaption = 'Select an image to convert...'
            img = QFileDialog.getOpenFileName(self,
                                              caption=fcaption,
                                              filter=ffilter)
            self.log.debug('image: %r', repr(img))
            if img[1]:
                self.append_tx_func([img[0]])
        else:
            fcaption = 'Select a directory to convert...'
            fld = QFileDialog.getExistingDirectory(self,
                                                   caption=fcaption)
            self.log.debug('dir: %s', repr(fld))
            if not fld:
                return
            imgs = []
            recursive = None
            for root, dirs, files in os.walk(fld):
                if recursive is None and dirs:
                    msg = QMessageBox()
                    msg.setText('Search sub-directories too ?')
                    msg.setInformativeText('This directory contains other directories that may contain more images.')
                    msg.setStandardButtons(QMessageBox.Ok | QMessageBox.No)
                    msg.setDefaultButton(QMessageBox.Ok)
                    msg.setEscapeButton(QMessageBox.No)
                    # trick to resize the QMessageBox width
                    msg.setStyleSheet('QLabel{min-width: 300px;}')
                    ret = msg.exec_()
                    recursive = ret == QMessageBox.Ok
                for f in files:
                    if os.path.splitext(f)[-1].lower() in txm.IMG_EXTENSIONS:
                        imgs.append(os.path.join(root, f))
                if recursive is False:
                    break
            self.log.debug('imgs = %s', imgs)
            self.append_tx_func(imgs)

    def update_ui(self, txfile_list=None):
        """
        Trigger an update of the TreeView.
        """
        # self.log.info("txfile_list=%r", txfile_list)
        if txfile_list is not None:
            if _is_valid(self.queue_list):
                self.queue_list.update_list(txfile_list)
            self._update_cache_size_ui()

        self.set_queue_button_state(self.txmanager.paused, block_signals=True)
        self.update_progress_bar(txfile_list=txfile_list)

    def update_file(self, args):
        """Update a single file and the progress bar when the ui_file_update
        signal is emitted."""
        txfile, txitem, state = args
        self.queue_list.update_file_status(txfile, state)
        if state in (txmc.STATE_EXISTS, txmc.STATE_MISSING, txmc.STATE_ERROR):
            self._update_cache_size_ui()
        if state in (txmc.STATE_EXISTS, txmc.STATE_IS_TEX):
            self.progress_bar.setValue(self.progress_bar.value() + 1)

    def _update_cache_size_ui(self):
        """Update the amount of disk space used by textures."""
        t_size, unit = self.total_cache_size()
        if _is_valid(self.tex_space):
            self.tex_space.setText(self.tx_diskspace_fmt % (t_size, unit))

    def update_progress_bar(self, txfile_list=None):
        """Sets the initial state of the progress bar by counting all files and
        checking their state."""
        if not _is_valid(self.progress_bar):
            return
        done = 0
        if txfile_list is not None:
            self.num_tasks = 0
            for txfile in txfile_list:
                for txitem in list(txfile.tex_dict.values()):
                    if txitem.state in (txmc.STATE_EXISTS, txmc.STATE_IS_TEX):
                        done += 1
                    self.num_tasks += 1
            # update max
            self.progress_bar.setTextVisible(self.num_tasks > 0)
            if self.num_tasks == 0:
                self.num_tasks = 1
            self.progress_bar.setRange(0, self.num_tasks)
            self.progress_bar.setValue(done)

    def display_selection_settings(self, modelIndex):
        """
        Update the settings area to reflect the current selection's
        settings.
        """
        # get select file path in queue widget.
        row = modelIndex.row()
        item = self.queue_list.root.child(row, 0)
        self.queue_list.curSelectedRow = row
        inputFile = item.text()

        # get the
        txFile = self.txmanager.get_txfile_from_path(inputFile)
        if not txFile:
            self.log.error('no TxFile for %r', inputFile)
            return

        params = txFile.get_params()
        if not params:
            self.log.error('no TxParams for %r', inputFile)
            return

        tx_type = params.get_texture_type()
        idx = txmp.TX_TYPES.index(tx_type)
        self.tx_type.setCurrentIndex(idx)

        tx_wrap = params.get_s_mode()
        try:
            idx = txmp.TX_WRAP_MODES.index(tx_wrap)
        except ValueError:
            self.tx_wrap_mode_s.setEnabled(False)
        else:
            self.tx_wrap_mode_s.setEnabled(True)
            self.tx_wrap_mode_s.setCurrentIndex(idx)

        tx_wrap = params.get_t_mode()
        try:
            idx = txmp.TX_WRAP_MODES.index(tx_wrap)
        except ValueError:
            self.tx_wrap_mode_t.setEnabled(False)
        else:
            self.tx_wrap_mode_t.setEnabled(True)
            self.tx_wrap_mode_t.setCurrentIndex(idx)

        tx_resize = params.get_resize()
        idx = txmp.TX_RESIZES.index(tx_resize)
        self.tx_resize.setCurrentIndex(idx)

        tx_filter = params.get_texture_filter()
        idx = txmp.TX_FILTERS.index(tx_filter)
        self.tx_filter.setCurrentIndex(idx)

        tx_format = params.get_texture_format()
        idx = txmp.TX_FORMATS.index(tx_format)
        self.tx_format.setCurrentIndex(idx)

        self.edited_file.edit(txFile)
        self.apply_but.setEnabled(False)

    def edit_param_value(self, *args):
        """
        Called when one of the textures settings controls value changes.

        Args:
        - combo box:
          - attr (str): the attribute's name
          - idx (int): the index of the selected menu item.
        """
        attr, idx = args
        self.log.debug('edit %s', repr(args))
        val = None
        if attr == 'texture_type':
            val = txmp.TX_TYPES[idx]
        if attr == 'smode':
            val = txmp.TX_WRAP_MODES[idx]
        if attr == 'tmode':
            val = txmp.TX_WRAP_MODES[idx]
        if attr == 'resize':
            val = txmp.TX_RESIZES[idx]
        if attr == 'texture_filter':
            val = txmp.TX_FILTERS[idx]
        if attr == 'texture_format':
            val = txmp.TX_FORMATS[idx]

        self.edited_file.set_param(attr, val)
        self.apply_but.setEnabled(self.edited_file.dirty)

    def apply_edit(self):
        """
        Sends modified settings to the texture manager.
        """
        self.log.debug('Apply new txmake params')
        self.edited_file.override_params()
        self.txmanager.txmake_all(start_queue=self.txmanager.paused is False)
        self.apply_but.setEnabled(False)

    def total_cache_size(self):
        """Compute the total disk space used by the scene's textures.

        Returns:
            tuple -- float size, string unit (MB or GB)
        """
        # import time
        # t_start = time.time()
        t_size = self.txmanager.file_size()
        # t_size in bytes
        t_size /= 1024.0 * 1024.0
        unit = 'MB'
        if t_size > 1024:
            t_size /= 1024.0
            unit = 'GB'
        # print 'total_cache_size computed in %.1f seconds' % (time.time()-t_start)
        return (t_size, unit)

    def clear_cache(self):
        """
        Delete all converted textures from disk and re-parse the scene to find
        images to convert.
        """
        t_size, unit = self.total_cache_size()
        reply = QMessageBox.warning(
            self, 'Are you sure ?',
            'This will delete %.1f %s of converted textures !' % (t_size, unit),
            QMessageBox.Ok | QMessageBox.Cancel, QMessageBox.Cancel)
        if reply == QMessageBox.Cancel:
            return
        self.log.debug('Start')
        self.txmanager.delete_texture_files()
        if self.parse_scene_func:
            self.parse_scene_func(start_queue=self.txmanager.paused is False)

    def toggle_queue(self, paused):
        """Pause / restart the txmake task queue.

        Arguments:
            paused {bool} -- True if a pause is requested.
        """
        if paused == self.txmanager.paused:
            # allows for a no-side-effect button state update.
            return

        self.txmanager.paused = paused
        if paused:
            self.txmanager.flush_queue()
            self.txmanager.update_ui_list()
            self.log.info('Texture Manager Paused !')
        else:
            self.parse_scene_func()
            self.log.info('Texture Manager Restarted !')

    def set_queue_button_state(self, paused, block_signals=False):
        """Reset the queue button to the start icon"""
        if self.pause_but.isChecked() == paused:
            return
        if block_signals:
            self.pause_but.blockSignals(True)
        self.pause_but.setChecked(paused)
        self.pause_but.setToolTip(TT_QUEUE_INFO[paused])
        if block_signals:
            self.pause_but.blockSignals(False)

    def toggle_settings(self, visible):
        if visible:
            if self.show_advanced:
                self.tx_settings.setFixedHeight(40 + 24 * 6)
            else:
                self.tx_settings.setFixedHeight(40 + 24 * 2)
            self.tx_settings.adjustSize()
        else:
            self.tx_settings.setFixedHeight(20)