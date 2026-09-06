/** OBSE editable message/journal session, hosted by SKSE's CustomMenu. */
class TES4TextInput {
  static var movie:MovieClip;
  static var field:TextField;
  static var buttons:Array;
  static var cursor:Number;
  static var enabled:Boolean;

  static function start(mc:MovieClip):Void {
    movie = mc;
    enabled = false;
    mc.TES4InputReady = true;
    mc.TES4InputActive = false;
    mc.TES4InputButton = -1;
    mc.TES4InputSetup = function(text:String, kind:String, limit:String):Void {
      TES4TextInput.setup(text, Number(kind), Number(limit));
    };
    mc.TES4InputUpdate = function():Void { TES4TextInput.update(); };
    mc.TES4InputInsert = function(text:String):Void { TES4TextInput.insert(text); };
    mc.TES4InputDelete = function(n:String, back:String, words:String):Void {
      TES4TextInput.erase(Number(n), Number(back) != 0, Number(words) != 0);
    };
    mc.TES4InputMove = function(n:String, back:String):Void {
      TES4TextInput.move(Number(n) * (Number(back) != 0 ? -1 : 1));
    };
    mc.TES4InputClose = function():Void { TES4TextInput.close(); };
    mc.onUnload = function():Void { TES4TextInput.release(); };
    mc.onEnterFrame = function():Void { TES4TextInput.update(); };
  }

  static function label(owner:MovieClip, name:String, depth:Number, x:Number,
                        y:Number, w:Number, h:Number, text:String, size:Number):TextField {
    owner.createTextField(name, depth, x, y, w, h);
    var t:TextField = owner[name];
    var format:TextFormat = new TextFormat("$EverywhereFont", size, 0xF3E8CD);
    t.setNewTextFormat(format);
    t.text = text;
    t.selectable = false;
    t.wordWrap = true;
    return t;
  }

  static function setup(text:String, kind:Number, limit:Number):Void {
    Stage.scaleMode = "showAll";
    Stage.align = "";
    movie.beginFill(0x161510, 97);
    movie.lineStyle(2, 0xA89568);
    movie.moveTo(240, 130); movie.lineTo(1040, 130);
    movie.lineTo(1040, 830); movie.lineTo(240, 830); movie.lineTo(240, 130);
    movie.endFill();
    movie.TES4InputKind = kind;
    var parts:Array = kind == 0 ? text.split("|") : ["Journal", "Finished"];
    if (parts.length == 1) parts.push("Finished");
    label(movie, "prompt", 1, 280, 160, 720, 130, parts[0], 24);
    field = label(movie, "entry", 2, 280, 300, 720, kind == 0 ? 50 : 370, "", 24);
    field.type = "input";
    field.selectable = true;
    field.multiline = kind != 0;
    field.wordWrap = kind != 0;
    field.maxChars = Math.max(1, Math.min(16384, limit));
    field.border = true;
    field.borderColor = 0xA89568;
    field.background = true;
    field.backgroundColor = 0x27241C;
    if (kind != 0) { field.html = true; field.htmlText = text; }
    cursor = field.text.length;
    buttons = [];
    for (var i:Number = 1; i < parts.length && i <= 10; i++) {
      var b:MovieClip = movie.createEmptyMovieClip("button" + i, 10 + i);
      b._x = 280 + ((i - 1) % 2) * 370;
      b._y = (kind == 0 ? 400 : 710) + Math.floor((i - 1) / 2) * 70;
      b.beginFill(0x4D4535); b.moveTo(0, 0); b.lineTo(350, 0);
      b.lineTo(350, 56); b.lineTo(0, 56); b.endFill();
      label(b, "caption", 1, 10, 9, 330, 45, parts[i], 20);
      b.index = i - 1;
      b.onRelease = function():Void { TES4TextInput.choose(this.index); };
      b.onRollOver = function():Void { this._alpha = 75; };
      b.onRollOut = function():Void { this._alpha = 100; };
      buttons.push(b);
    }
    movie.TES4InputActive = true;
    movie.TES4InputButton = -1;
    if (!enabled) { _global.skse.AllowTextInput(true); enabled = true; }
    Selection.setFocus(field);
    Selection.setSelection(cursor, cursor);
    update();
  }

  static function update():Void {
    if (!movie.TES4InputActive) return;
    if (Selection.getFocus() == String(field)) cursor = Math.max(0, Selection.getCaretIndex());
    movie.TES4InputText = movie.TES4InputKind == 0 ? field.text : field.htmlText;
    movie.TES4InputPlainText = field.text;
    movie.TES4InputCursor = cursor;
  }

  static function move(n:Number):Void {
    cursor = Math.max(0, Math.min(field.text.length, cursor + n));
    Selection.setFocus(field);
    Selection.setSelection(cursor, cursor);
    update();
  }

  static function insert(text:String):Void {
    update();
    text = text.substr(0, Math.max(0, field.maxChars - field.text.length));
    field.text = field.text.substr(0, cursor) + text + field.text.substr(cursor);
    move(text.length);
  }

  static function erase(n:Number, back:Boolean, words:Boolean):Void {
    update();
    var end:Number = cursor;
    var step:Number = back ? -1 : 1;
    if (words) {
      for (var i:Number = 0; i < n; i++) {
        while (end + step >= 0 && end + step <= field.text.length &&
               field.text.charAt(back ? end - 1 : end) == " ") end += step;
        while (end + step >= 0 && end + step <= field.text.length &&
               field.text.charAt(back ? end - 1 : end) != " ") end += step;
      }
    } else end = Math.max(0, Math.min(field.text.length, cursor + n * step));
    var start:Number = Math.min(cursor, end);
    field.text = field.text.substr(0, start) + field.text.substr(Math.max(cursor, end));
    cursor = start;
    move(0);
  }

  static function choose(index:Number):Void {
    update();
    movie.TES4InputButton = index;
  }

  static function release():Void {
    if (enabled) { _global.skse.AllowTextInput(false); enabled = false; }
    movie.TES4InputActive = false;
  }

  static function close():Void {
    release();
    _global.skse.CloseMenu("CustomMenu");
  }
}
