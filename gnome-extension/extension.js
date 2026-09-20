import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';

export default class BenedictFocusExtension extends Extension {
    enable() {
        this._path = GLib.build_filenamev([GLib.get_user_runtime_dir(), 'benedict-focus']);
        this._handler = global.display.connect('notify::focus-window', () => this._write());
        this._write();
    }

    disable() {
        if (this._handler) {
            global.display.disconnect(this._handler);
            this._handler = null;
        }
    }

    _write() {
        const window = global.display.focus_window;
        const wmClass = window ? window.get_wm_class() || '' : '';
        try {
            Gio.File.new_for_path(this._path).replace_contents(
                wmClass, null, false, Gio.FileCreateFlags.REPLACE_DESTINATION, null);
        } catch (error) {
            logError(error);
        }
    }
}
