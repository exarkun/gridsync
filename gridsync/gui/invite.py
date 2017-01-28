# -*- coding: utf-8 -*-

import json
import os

from PyQt5.QtCore import Qt, QStringListModel
from PyQt5.QtGui import QFont, QPixmap
from PyQt5.QtWidgets import (
    QCheckBox, QCompleter, QGridLayout, QLabel, QLineEdit, QMessageBox,
    QProgressBar, QSizePolicy, QSpacerItem, QStackedWidget, QWidget)
from twisted.internet import reactor
from twisted.internet.defer import CancelledError, inlineCallbacks
from wormhole.errors import WrongPasswordError
from wormhole.wordlist import raw_words
from wormhole.xfer_util import receive

from gridsync import config_dir, resource
from gridsync import settings as global_settings
from gridsync.tahoe import Tahoe


wordlist = []
for word in raw_words.items():
    wordlist.extend(word[1])
wordlist = sorted([word.lower() for word in wordlist])


def is_valid(code):
    words = code.split('-')
    if len(words) != 3:
        return False
    elif not words[0].isdigit():
        return False
    elif not words[1] in wordlist:
        return False
    elif not words[2] in wordlist:
        return False
    else:
        return True


class Completer(QCompleter):
    def __init__(self):
        super(self.__class__, self).__init__()
        self.setCaseSensitivity(Qt.CaseInsensitive)
        self.setMaxVisibleItems(5)
        #self.setCompletionMode(QCompleter.UnfilteredPopupCompletion)
        self.setCompletionMode(QCompleter.InlineCompletion)

    def pathFromIndex(self, index):
        path = QCompleter.pathFromIndex(self, index)
        words = self.widget().text().split('-')
        if len(words) > 1:
            path = '{}-{}'.format('-'.join(words[:-1]), path)
        return path

    def splitPath(self, path):  # pylint: disable=no-self-use
        return [str(path.split('-')[-1])]


class LineEdit(QLineEdit):
    def __init__(self, parent=None):
        super(self.__class__, self).__init__()
        self.parent = parent
        font = QFont()
        font.setPointSize(16)
        model = QStringListModel()
        model.setStringList(wordlist)
        completer = Completer()
        completer.setModel(model)
        self.setFont(font)
        self.setCompleter(completer)
        self.setAlignment(Qt.AlignCenter)
        #self.setPlaceholderText("Enter invite code")

    def keyPressEvent(self, event):
        key = event.key()
        text = self.text()
        if key == Qt.Key_Space:
            if text and not text.endswith('-'):
                self.setText(text + '-')
        elif key == Qt.Key_Tab:
            if text and len(text.split('-')) < 3 and not text.endswith('-'):
                self.setText(text + '-')
            else:
                self.setText(text)
        elif key == Qt.Key_Escape:
            if text:
                self.parent.reset()
            #else:
            #    self.parent.close()
        else:
            return QLineEdit.keyPressEvent(self, event)


class CodeEntryWidget(QWidget):
    def __init__(self, parent=None):
        super(self.__class__, self).__init__()
        self.parent = parent

        pixmap = QPixmap(resource('mail-envelope-closed.png')).scaled(128, 128)
        self.icon = QLabel()
        self.icon.setPixmap(pixmap)
        self.icon.setAlignment(Qt.AlignCenter)

        self.label = QLabel("Enter invite code:")
        font = QFont()
        font.setPointSize(14)
        self.label.setFont(font)
        self.label.setStyleSheet("color: grey")
        self.label.setAlignment(Qt.AlignCenter)

        self.lineedit = LineEdit(self)
        self.lineedit.returnPressed.connect(self.parent.return_pressed)

        self.checkbox = QCheckBox(self)
        self.checkbox.setText("Always connect using Tor")
        self.checkbox.setEnabled(True)
        self.checkbox.setCheckable(False)
        self.checkbox.setStyleSheet("color: grey")
        self.checkbox.setFocusPolicy(Qt.NoFocus)

        self.message = QLabel('hey')
        self.message.setStyleSheet("color: red")
        self.message.setAlignment(Qt.AlignCenter)
        self.message.hide()

        layout = QGridLayout(self)
        layout.addItem(QSpacerItem(0, 0, 0, QSizePolicy.Expanding), 0, 0)
        layout.addItem(QSpacerItem(0, 0, QSizePolicy.Expanding, 0), 1, 1)
        layout.addItem(QSpacerItem(0, 0, QSizePolicy.Expanding, 0), 1, 2)
        layout.addWidget(self.icon, 1, 3)
        layout.addItem(QSpacerItem(0, 0, QSizePolicy.Expanding, 0), 1, 4)
        layout.addItem(QSpacerItem(0, 0, QSizePolicy.Expanding, 0), 1, 5)
        layout.addWidget(self.label, 2, 3, 1, 1)
        layout.addWidget(self.lineedit, 3, 2, 1, 3)
        layout.addWidget(self.checkbox, 4, 3)
        layout.addWidget(self.message, 4, 3)
        layout.addItem(QSpacerItem(0, 0, 0, QSizePolicy.Expanding), 5, 1)

    def show_error(self, message):
        self.message.setText(message)
        self.checkbox.hide()
        self.message.show()
        reactor.callLater(3, self.message.hide)
        reactor.callLater(3, self.checkbox.show)

    def reset(self):
        self.lineedit.setText('')


class ProgressBarWidget(QWidget):
    def __init__(self):
        super(self.__class__, self).__init__()
        self.step = 0

        pixmap = QPixmap(resource('mail-envelope-open.png')).scaled(128, 128)
        self.icon = QLabel()
        self.icon.setPixmap(pixmap)
        self.icon.setAlignment(Qt.AlignCenter)
        self.progressbar = QProgressBar()
        self.progressbar.setMaximum(7)
        self.progressbar.setTextVisible(False)
        self.message = QLabel()
        self.message.setStyleSheet("color: grey")
        self.message.setAlignment(Qt.AlignCenter)

        layout = QGridLayout(self)
        layout.addItem(QSpacerItem(0, 0, 0, QSizePolicy.Expanding), 0, 0)
        layout.addItem(QSpacerItem(0, 0, QSizePolicy.Expanding, 0), 1, 1)
        layout.addItem(QSpacerItem(0, 0, QSizePolicy.Expanding, 0), 1, 2)
        layout.addWidget(self.icon, 1, 3)
        layout.addItem(QSpacerItem(0, 0, QSizePolicy.Expanding, 0), 1, 4)
        layout.addItem(QSpacerItem(0, 0, QSizePolicy.Expanding, 0), 1, 5)
        layout.addWidget(self.progressbar, 2, 2, 1, 3)
        layout.addWidget(self.message, 3, 3)
        layout.addItem(QSpacerItem(0, 0, 0, QSizePolicy.Expanding), 4, 1)

    def update_progress(self, step, message):
        self.step = step
        self.progressbar.setValue(step)
        self.message.setText(message)

    def reset(self):
        self.update_progress(0, '')


class InviteForm(QStackedWidget):
    def __init__(self):
        super(self.__class__, self).__init__()
        self.resize(500, 333)
        self.page_1 = CodeEntryWidget(self)
        self.page_2 = ProgressBarWidget()

        self.addWidget(self.page_1)
        self.addWidget(self.page_2)

    def update_progress(self, step, message):
        self.page_2.update_progress(step, message)

    def show_error(self, message):
        self.page_1.show_error(message)

    def reset(self):
        self.page_1.reset()
        self.page_2.reset()
        self.setCurrentIndex(0)

    @inlineCallbacks
    def setup(self, settings):
        settings = json.loads(settings)
        folder = os.path.join(os.path.expanduser('~'), 'Private')
        try:
            os.makedirs(folder)
        except OSError:
            pass

        self.update_progress(2, 'Creating gateway...')
        tahoe = Tahoe(os.path.join(config_dir, 'default'))
        yield tahoe.create(**settings)

        self.update_progress(3, 'Starting gateway...')
        yield tahoe.start()

        self.update_progress(4, 'Connecting to grid...')
        yield tahoe.await_ready()

        self.update_progress(5, 'Creating magic-folder...')
        yield tahoe.command(['magic-folder', 'create', 'magic:', 'admin',
                             folder])

        self.update_progress(6, 'Reloading...')
        yield tahoe.start()

        self.update_progress(7, 'Done!')
        yield tahoe.await_ready()
        # TODO: Open local folder with file manager instead?
        yield tahoe.command(['webopen'])
        self.close()

    def show_failure(self, failure):
        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Warning)
        msg.setStandardButtons(QMessageBox.Retry)
        msg.setEscapeButton(QMessageBox.Retry)
        msg.setDetailedText(str(failure))
        if failure.type == WrongPasswordError:
            self.show_error("Invite confirmation failed")
            msg.setWindowTitle("Invite confirmation failed")
            msg.setText(
                "Either you mistyped your invite code, or a potential "
                "attacker tried to guess your code and failed. To try "
                "again, you will need to obtain a new invite code from "
                "your inviter.")  # or "service provider"?
        elif failure.type == json.decoder.JSONDecodeError:
            self.show_error("Invalid response")
            msg.setIcon(QMessageBox.Critical)
            msg.setWindowTitle("Invalid response")
            msg.setText(
                "Your invite code worked but your inviter did not provide "
                "the information needed to complete the invitation process. "
                "Please let them know about the error, and try again later "
                "with a new invite code.")
        elif failure.type == CancelledError and self.step == 1:
            self.show_error("Invite timed out")
            msg.setWindowTitle("Invite timed out")
            msg.setText(
                "The invitation process has timed out. Your invite code may "
                "have expired. Please request a new invite code from your "
                "inviter and try again.")
        # XXX: Other errors?
        else:
            return
        msg.exec_()
        self.reset()

    def return_pressed(self):
        code = self.page_1.lineedit.text().lower()
        if is_valid(code):
            self.setCurrentIndex(1)
            self.update_progress(1, 'Opening wormhole...')
            d = receive(reactor, global_settings['wormhole']['appid'],
                        global_settings['wormhole']['relay'], code)
            d.addCallback(self.setup)
            d.addErrback(self.show_failure)
            reactor.callLater(5, d.cancel)
        else:
            self.show_error("Invalid code")
