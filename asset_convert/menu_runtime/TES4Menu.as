/** TES4 XML tile evaluator for Skyrim's SKSE CustomMenu. */
class TES4Menu {
  static var movie:MovieClip;
  static var nodes:Array;
  static var root:Object;
  static var serial:Number;
  static var frame:Number;
  static var templates:Object;

  static function start(mc:MovieClip, layout:Array):Void {
    movie = mc;
    nodes = [];
    serial = 1;
    frame = 0;
    templates = {};
    Stage.scaleMode = "noScale";
    Stage.align = "TL";
    root = {name:"", clip:mc, children:[], traits:{}, values:{}, marks:{}};
    create(layout, root);
    mc.TES4Values = root.children[0].values;
    mc.TES4Traits = root.children[0].present;
    for (var i:Number = 0; i < nodes.length; i++) {
      var n:Object = nodes[i];
      n.parent.values[n.name] = n.values;
      if (n.parent.present != undefined) n.parent.present[n.name] = n.present;
      mc.TES4Values[n.name] = n.values;
      mc.TES4Traits[n.name] = n.present;
    }
    mc.TES4SetString = function(path:String, value:String):Void { TES4Menu.setValue(path, value); };
    mc.TES4SetNumber = function(path:String, value:String):Void { TES4Menu.setValue(path, Number(value)); };
    mc.TES4Query = function(path:String):Void { mc.TES4Result = TES4Menu.query(path); };
    mc.TES4Click = function(path:String):Void { TES4Menu.click(TES4Menu.find(path, TES4Menu.root)); };
    mc.TES4Ready = true;
    mc.onEnterFrame = function():Void { TES4Menu.update(); };
    var keys:Object = {};
    keys.onKeyDown = function():Void {
      if (Key.getCode() == Key.ESCAPE || Key.getCode() == Key.TAB) {
        TES4Menu.send("OnClose", TES4Menu.root);
        _global.skse.CloseMenu("CustomMenu");
      }
    };
    Key.addListener(keys);
    var mouse:Object = {};
    mouse.onMouseMove = function():Void {
      var next:Object = TES4Menu.pick();
      if (this.hover != next) {
        if (this.hover != undefined) this.hover.values.mouseover = 0;
        this.hover = next;
        if (next != undefined) {
          next.values.mouseover = 1;
          TES4Menu.send("OnMouseOver", next);
        }
      }
    };
    mouse.onMouseDown = function():Void { this.pressed = TES4Menu.pick(); };
    mouse.onMouseUp = function():Void {
      var target:Object = TES4Menu.pick();
      if (target == this.pressed) TES4Menu.click(target);
      this.pressed = undefined;
    };
    Mouse.addListener(mouse);
    update();
    send("OnOpen", root);
  }

  static function create(items:Array, parent:Object):Void {
    for (var i:Number = 0; i < items.length; i++) {
      var item:Object = items[i];
      if (item.trait != undefined) {
        parent.traits[item.trait] = item.value;
      } else if (item.template != undefined) {
        templates[item.template] = item.items;
      } else {
        var node:Object = {name:item.name, kind:item.kind, parent:parent,
          children:[], traits:{}, values:{}, present:{}, marks:{}, busy:{}, dependencies:{}, serial:serial++};
        node.clip = parent.clip.createEmptyMovieClip("tile" + node.serial, node.serial);
        parent.children.push(node);
        nodes.push(node);
        if (node.kind == "text") {
          node.clip.createTextField("label", 1, 0, 0, 100, 100);
          node.text = node.clip.label;
          node.text.selectable = false;
          node.text.html = true;
          node.text.multiline = true;
          node.text.wordWrap = true;
        }
        create(item.items, node);
      }
    }
  }

  static function menu(node:Object):Object {
    while (node.parent != root && node.parent != undefined) node = node.parent;
    return node;
  }

  static function find(path:String, here:Object):Object {
    if (path == "me()") return here;
    if (path == "parent()") return here.parent;
    if (path == "menu()") return menu(here);
    if (path == "screen()") return {values:{width:1280, height:960}};
    if (path == "strings()") return {values:{_exit:"Exit", _take:"Take", _prev:"Previous", _next:"Next"}};
    if (path == "sibling()") {
      var siblings:Array = here.parent.children;
      for (var s:Number = 1; s < siblings.length; s++) if (siblings[s] == here) return siblings[s - 1];
      return undefined;
    }
    if (path.substr(0, 8) == "sibling(") {
      var siblingName:String = path.substring(8, path.length - 1).toLowerCase();
      for (var si:Number = 0; si < here.parent.children.length; si++)
        if (here.parent.children[si].name.toLowerCase() == siblingName) return here.parent.children[si];
      return undefined;
    }
    if (path.substr(0, 6) == "child(") {
      var childName:String = path.substring(6, path.length - 1).toLowerCase();
      for (var c:Number = 0; c < here.children.length; c++)
        if (here.children[c].name.toLowerCase() == childName) return here.children[c];
      return undefined;
    }
    var parts:Array = path.split("\\").join("/").split("/");
    var first:String = String(parts.shift()).toLowerCase();
    var node:Object;
    if (first == "") node = menu(here);
    for (var i:Number = 0; i < nodes.length; i++)
      if (nodes[i].name.toLowerCase() == first) { node = nodes[i]; break; }
    while (node != undefined && parts.length) {
      var name:String = String(parts.shift()).toLowerCase();
      var next:Object;
      for (var j:Number = 0; j < node.children.length; j++)
        if (node.children[j].name.toLowerCase() == name) { next = node.children[j]; break; }
      node = next;
    }
    return node;
  }

  static function read(node:Object, name:String):Object {
    if (node == undefined) return 0;
    if (node.traits == undefined || node.traits[name] == undefined) {
      if (node.values[name] != undefined) return node.values[name];
      if (name == "alpha") return 255;
      if (name == "visible") return 2;
      if (name == "font") return 1;
      return 0;
    }
    if (node.marks[name] == frame || node.busy[name]) return node.values[name] == undefined ? 0 : node.values[name];
    node.busy[name] = true;
    var old:Object = node.values[name] == undefined ? 0 : node.values[name];
    var evaluated:Array = evaluate(node.traits[name], node, old);
    var result:Object = node.dependencies[name] == evaluated[1] ? old : evaluated[0];
    node.dependencies[name] = evaluated[1];
    node.busy[name] = false;
    node.values[name] = result;
    node.marks[name] = frame;
    return result;
  }

  static function evaluate(expr:Object, node:Object, initial:Object):Array {
    if (!(expr instanceof Array)) return [expr, typeof(expr) + ":" + expr];
    var value:Object = initial;
    var signature:String = "";
    for (var i:Number = 0; i < expr.length; i++) {
      var op:Array = expr[i];
      var right:Object;
      if (op[1] != "") {
        var trait:String = op[2];
        // TES4's indexed trait lookup uses the accumulated value as suffix.
        if (trait.charAt(trait.length - 1) == "_") trait += String(value);
        right = read(find(op[1], node), trait);
      } else right = evaluate(op[3], node, 0)[0];
      signature += op[0] + ":" + typeof(right) + ":" + String(right).length + ":" + right + ";";
      var a:Number = Number(value), b:Number = Number(right);
      switch (op[0]) {
        case "copy": case "ref": value = right; break;
        case "add": value = a + b; break;
        case "sub": value = a - b; break;
        case "mul": case "mult": value = a * b; break;
        case "div": value = b == 0 ? 0 : a / b; break;
        case "mod": value = a % b; break;
        case "rand":
          // Authored UI indexes random choices from 1 through the operand.
          // Keep the sample until that operand changes, as other traits do.
          if (op[4] == undefined) op[4] = {};
          var sample:Object = op[4][node.serial];
          if (sample == undefined || sample.bound != b) {
            sample = {bound:b, value:b > 0 ? 1 + Math.floor(Math.random() * Math.floor(b)) : 0};
            op[4][node.serial] = sample;
          }
          value = sample.value;
          break;
        case "min": value = Math.min(a, b); break;
        case "max": value = Math.max(a, b); break;
        case "floor": value = Math.floor(a); break;
        case "ceil": value = Math.ceil(a); break;
        case "round": value = Math.round(a); break;
        case "abs": value = Math.abs(a); break;
        case "eq": value = value == right ? 2 : 1; break;
        case "neq": value = value != right ? 2 : 1; break;
        case "gt": value = a > b ? 2 : 1; break;
        case "gte": value = a >= b ? 2 : 1; break;
        case "lt": value = a < b ? 2 : 1; break;
        case "lte": value = a <= b ? 2 : 1; break;
        case "and": value = a == 2 && b == 2 ? 2 : 1; break;
        case "or": value = a == 2 || b == 2 ? 2 : 1; break;
        case "not": value = b == 2 ? 1 : 2; break;
        case "onlyif": if (b != 2) value = 0; break;
        case "onlyifnot": case "onlynotif": if (b == 2) value = 0; break;
      }
    }
    return [value, signature];
  }

  static function traitPath(path:String):Array {
    var parts:Array = path.split("\\").join("/").split("/");
    var trait:String = String(parts.pop()).toLowerCase();
    return [parts.length ? find(parts.join("/"), root.children[0]) : root.children[0], trait];
  }
  static function setValue(path:String, value:Object):Void {
    var pair:Array = traitPath(path);
    if (pair[0] != undefined) pair[0].traits[pair[1]] = value;
    update();
  }
  static function query(path:String):Object {
    var pair:Array = traitPath(path);
    movie.TES4Found = pair[0] != undefined && (pair[0].traits[pair[1]] != undefined || pair[0].values[pair[1]] != undefined);
    return read(pair[0], pair[1]);
  }
  static function send(event:String, node:Object):Void {
    if (_global.skse != undefined) _global.skse.SendModEvent("TES4Menu_" + event,
      node.name, Number(read(node, "id")));
  }
  static function click(node:Object):Void {
    if (node == undefined) return;
    node.values.clicked = 1;
    update();
    send("OnClick", node);
    node.values.clicked = 0;
    if (Number(read(node, "id")) == 31) _global.skse.CloseMenu("CustomMenu");
  }

  static function pick():Object {
    var point:Object = {x:movie._xmouse, y:movie._ymouse};
    movie.localToGlobal(point);
    var best:Object;
    for (var i:Number = 0; i < nodes.length; i++) {
      var n:Object = nodes[i], p:Object = n;
      var visible:Boolean = true;
      while (p != root) { if (!p.clip._visible) visible = false; p = p.parent; }
      var local:Object = {x:point.x, y:point.y};
      n.clip.globalToLocal(local);
      if (!visible || read(n, "target") != 2 || local.x < 0 || local.y < 0 ||
          local.x > Number(read(n, "width")) || local.y > Number(read(n, "height"))) continue;
      if (best == undefined || inFront(n, best)) best = n;
    }
    return best;
  }

  static function inFront(a:Object, b:Object):Boolean {
    var aa:Array = [], bb:Array = [];
    while (a != root) { aa.unshift(a); a = a.parent; }
    while (b != root) { bb.unshift(b); b = b.parent; }
    var i:Number = 0;
    while (i < aa.length && i < bb.length && aa[i] == bb[i]) i++;
    if (i == aa.length || i == bb.length) return aa.length > bb.length;
    return aa[i].clip.getDepth() > bb[i].clip.getDepth();
  }

  static function update():Void {
    frame++;
    for (var i:Number = 0; i < nodes.length; i++) {
      var n:Object = nodes[i];
      var mc:MovieClip = n.clip;
      for (var trait:String in n.traits) {
        n.present[trait] = true;
        read(n, trait);
      }
      mc._x = Number(read(n, "x")); mc._y = Number(read(n, "y"));
      mc._visible = read(n, "visible") != 1;
      mc._alpha = n.kind == "menu" ? 100 : Number(read(n, "alpha")) / 2.55;
      var depth:Number = Number(read(n, "depth")) * 1000 + n.serial;
      if (mc.getDepth() != depth) mc.swapDepths(depth);
      var width:Number = Number(read(n, "width")), height:Number = Number(read(n, "height"));
      if (n.kind == "image") {
        var filename:String = String(read(n, "filename"));
        if (filename != "0" && n.filename != filename) {
          n.filename = filename;
          var image:MovieClip = mc.createEmptyMovieClip("image", 0);
          var loader:MovieClipLoader = new MovieClipLoader();
          loader.loadClip("img://textures/tes4/" + filename.split("\\").join("/"), image);
        }
        if (mc.image._width > 0 && width > 0) mc.image._width = width;
        if (mc.image._height > 0 && height > 0) mc.image._height = height;
        n.values.filewidth = mc.image._width; n.values.fileheight = mc.image._height;
      } else if (n.kind == "text") {
        var text:TextField = n.text;
        var wrap:Number = Number(read(n, "wrapwidth"));
        text.autoSize = wrap > 0 ? "none" : "left";
        text.wordWrap = wrap > 0;
        if (wrap > 0) text._width = wrap;
        var limit:Number = Number(read(n, "wraplimit"));
        text._height = limit > 0 ? limit : (height > 0 ? height : 800);
        var format:TextFormat = new TextFormat();
        var fontID:Number = Number(read(n, "font"));
        format.font = fontID == 5 ? "$HandwrittenFont" : fontID == 4 ? "$DaedricFont" : "$SkyrimBooks";
        format.size = 28;
        format.color = (Number(read(n, "red")) << 16) | (Number(read(n, "green")) << 8) | Number(read(n, "blue"));
        var justify:Number = Number(read(n, "justify"));
        format.align = wrap > 0 && justify == 2 ? "center" : (wrap > 0 && justify == 4 ? "right" : "left");
        text.setNewTextFormat(format);
        var content:String = String(read(n, "string"));
        if (content == "0") content = "";
        var layoutKey:String = content + "|" + wrap + "|" + limit + "|" + format.font;
        if (n.layoutKey != layoutKey) {
          text.htmlText = content;
          text.setTextFormat(format);
          n.layoutKey = layoutKey;
          n.pages = [1];
          if (limit > 0) {
            text.scroll = text.maxscroll;
            var lastLine:Number = text.bottomScroll;
            text.scroll = 1;
            var blank:String = "";
            for (var pad:Number = 0; pad < text.bottomScroll; pad++) blank += "<br>";
            text.htmlText = content + blank;
            text.setTextFormat(format);
            text.scroll = 1;
            while (text.bottomScroll < lastLine) {
              var startLine:Number = text.bottomScroll + 1;
              text.scroll = startLine;
              if (text.scroll != startLine) break;
              n.pages.push(startLine);
            }
          }
        }
        n.values.pagecount = n.pages.length;
        text.scroll = n.pages[Math.min(n.pages.length - 1, Number(read(n, "pagenum")))];
        text._x = wrap > 0 ? 0 : (justify == 2 ? -text._width / 2 : (justify == 4 ? -text._width : 0));
        n.values.width = text._width;
        n.values.height = text.textHeight;
      }
    }
    movie._xscale = Stage.width / 1280 * 100;
    movie._yscale = Stage.height / 960 * 100;
  }
}
