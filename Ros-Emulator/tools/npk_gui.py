#!/usr/bin/env python3
"""
RoS NeoX NPK Studio & Visual Asset Inspector (v5.0 Ultimate 3D)
- True NeoX Triangle Strip Unpacker: Accurate 3D weapon/character geometry with zero distortion.
- 100% Comprehensive Pre-Classification on load (DDS, XML, Mesh, Rig, Audio, Script).
- High-definition 3D Viewport with Solid Lighting, Wireframe, and Free 360° Orbit.
- Texture Image Viewer with Alpha Checkerboard.
"""

import os
import sys
import struct
import zlib
import math
import mmap
import threading
import time
import io
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import customtkinter as ctk
from PIL import Image, ImageTk

# ---- Recovered NeoX Rotor Key & Decryptor ----
KEY = (b"zxp+3uexi,fjepkfap3341s~mnv+1we!/zxp+3uexi,fj$~ap3341sfjepkfap3341s+3uexi"
       b"fjepkfap3341exi,+3uex22i,+3t56uexi,+3ue34xi,+3u34exi,+tttuexi,+lzuexi,~mnv"
       b"+1we!/zxp~mnv+1we!/zxp*&sfjepkfap3341sfjepkf1!,fjepkfap3341s~mnv+1we!/epkf"
       b"ap3341s~mnv+1we!/zxp+3uexi,fjepkfap3341s~mnv+1we!/zxp+3uexi,fjepkfap3341s~"
       b"mnv+1we!/zxp!#+3u'")

def _cmod(a, b): r = abs(a) % abs(b); return r if a >= 0 else -r
def _cdiv(a, b): q = abs(a) // abs(b); return q if (a < 0) == (b < 0) else -q
def _s16(v): v &= 0xffff; return v - 0x10000 if v >= 0x8000 else v

class Rotor:
    def __init__(self, key, n=6):
        self.size = 256; self.rotors = n
        self.e = bytearray(n * 256); self.d = bytearray(n * 256)
        self.pos = [0] * n; self.adv = [0] * n; self.seed = [0, 0, 0]
        k1, k2, k3, k4, k5 = 995, 576, 767, 671, 463
        for ch in key:
            ki = ch & 0xff
            k1 = ((k1 << 3 | k1 >> 13) + ki) & 65535; k2 = ((k2 << 3 | k2 >> 13) ^ ki) & 65535
            k3 = ((k3 << 3 | k3 >> 13) - ki) & 65535; k4 = (ki - (k4 << 3 | k4 >> 13)) & 65535
            k5 = ((k5 << 3 | k5 >> 13) ^ (0xFFFF ^ ki)) & 65535
        self.key = [_s16(k1), _s16(k2 | 1), _s16(k3), _s16(k4), _s16(k5)]

    def _rand(self, s):
        x, y, z = self.seed
        x = 171 * _cmod(x, 177) - 2 * _cdiv(x, 177)
        y = 172 * _cmod(y, 176) - 35 * _cdiv(y, 176)
        z = 170 * _cmod(z, 178) - 63 * _cdiv(z, 178)
        if x < 0: x += 30269
        if y < 0: y += 30307
        if z < 0: z += 30323
        self.seed = [x, y, z]
        t = x / 30269.0 + y / 30307.0 + z / 30323.0
        v = t - math.floor(t)
        return int((0.0 if v >= 1.0 else v) * s) % s

    def _init(self):
        self.seed = [self.key[0], self.key[1], self.key[2]]
        ident = bytes(range(256))
        for i in range(self.rotors):
            self.e[i * 256:(i + 1) * 256] = ident; self.d[i * 256:(i + 1) * 256] = ident
            self.pos[i] = 1; self.adv[i] = 1
        for i in range(self.rotors):
            base = i * 256; self.pos[i] = self._rand(256); self.adv[i] = 1 + 2 * self._rand(128)
            e, d = self.e, self.d; ii = 256
            while 2 <= ii:
                q = self._rand(ii); ii -= 1; j = e[base + q]; e[base + q] = e[base + ii]; e[base + ii] = j; d[base + j] = ii
            d[base + e[base]] = 0

    def _adv1(self):
        for i in range(self.rotors):
            t = self.pos[i] + self.adv[i]; self.pos[i] = t % 256
            if t >= 256 and i < self.rotors - 1:
                self.pos[i + 1] = (1 + self.pos[i + 1]) & 0xFF

    def decrypt(self, data):
        self._init(); out = bytearray(len(data)); R = self.rotors; dr = self.d; pos = self.pos
        for n, c in enumerate(data):
            tc = c; i = R - 1
            while 0 <= i:
                tc = (pos[i] ^ dr[i * 256 + tc]) % 256
                i -= 1
            out[n] = tc; self._adv1()
        return bytes(out)

def reverse_string(b):
    l = bytearray(b)
    for i in range(min(128, len(l))): l[i] ^= 154
    l.reverse()
    return bytes(l)

def deob(b):
    L = len(b)
    return bytes((c ^ ((L - 1 - k) & 0xff)) for k, c in enumerate(b))

def decrypt_script_raw(raw):
    try:
        return reverse_string(zlib.decompress(Rotor(KEY, 6).decrypt(raw)))
    except Exception:
        return None

# ---- Fast Py2.7 Unmarshaller ----
class PyUnmarshaller:
    def __init__(self, b):
        self.b = b; self.i = 0; self.refs = []
    def i32(self):
        v = struct.unpack_from('<i', self.b, self.i)[0]; self.i += 4; return v
    def load(self):
        if self.i >= len(self.b): return None
        t = self.b[self.i] & 0x7f; self.i += 1; c = chr(t)
        if c == 'c':
            for _ in range(4): self.i32()
            code = self.load(); consts = self.load(); names = self.load(); varnames = self.load()
            free = self.load(); cell = self.load(); fn = self.load(); nm = self.load()
            self.i32(); ln = self.load()
            return {'code': code, 'consts': consts, 'names': names, 'varnames': varnames, 'file': fn, 'name': nm}
        if c in ('s', 't', 'u'):
            n = self.i32(); v = deob(self.b[self.i:self.i + n]); self.i += n
            if c == 't': self.refs.append(v)
            return v
        if c == 'R':
            idx = self.i32(); return self.refs[idx] if 0 <= idx < len(self.refs) else b''
        if c in ('(', '[', '<', '>'):
            n = self.i32(); return [self.load() for _ in range(n)]
        if c == 'N': return None
        if c in ('T', 'F', '.'): return c
        if c == 'i': return self.i32()
        if c == 'I': self.i += 8; return 0
        if c == 'l':
            n = self.i32()
            for _ in range(abs(n)): self.i += 2
            return 0
        if c == 'g': self.i += 8; return 0.0
        if c == 'f':
            n = self.b[self.i]; self.i += 1; self.i += n; return 0.0
        return None

def dec_str(x):
    if isinstance(x, bytes):
        try: return x.decode('utf-8')
        except Exception:
            try: return x.decode('latin1')
            except Exception: return repr(x)
    return str(x) if x is not None else ''

# ---- Complete Asset Classifier ----
def classify_header_data(head, raw_head=b""):
    if not head:
        if raw_head[:2] == b'\x7a\x1c':
            return "Python Script (.py)", "script", ".py"
        return "Binary Asset (.bin)", "binary", ".bin"

    if head.startswith(b'\xef\xbb\xbf'):
        head = head[3:]

    # Textures / Images
    if head[:4] == b'DDS ':
        try:
            h, w = struct.unpack_from('<II', head, 12)
            fourcc = head[84:88].decode('latin1', 'ignore').strip() if len(head) >= 88 else ""
            fmt = fourcc if fourcc else "DXT1"
            return f"Texture DDS ({fmt} {w}x{h})", "image", ".dds"
        except Exception:
            return "Texture DDS (.dds)", "image", ".dds"
    elif head[:8] == b'\x89PNG\r\n\x1a\n':
        try:
            w, h = struct.unpack_from('>II', head, 16)
            return f"PNG Image ({w}x{h})", "image", ".png"
        except Exception:
            return "PNG Image (.png)", "image", ".png"
    elif head[:3] == b'\xff\xd8\xff':
        return "JPEG Image (.jpg)", "image", ".jpg"

    # XML / Configs / Text
    if head[:5] in (b'<?xml', b'<NeoX', b'<Mate', b'<Enti', b'<Root', b'<Item', b'<Game', b'<Scen') or head.strip().startswith(b'<'):
        return "XML / Model Config (.xml)", "text", ".xml"
    if head[:1] in (b'{', b'[') and (b'"' in head or b':' in head):
        return "JSON Config (.json)", "text", ".json"

    # 3D Meshes & Rigging
    if head[:4] == b'4\x80\xc8\xbb' or head[:4] == b'\x34\x80\xc8\xbb':
        return "NeoX 3D Mesh (.mesh)", "mesh", ".mesh"
    if head[:4] == b'RGIS':
        return "Skeleton Rig (.rig)", "rig", ".rig"
    if head[:4] in (b'MODL', b'MESH'):
        return "3D Model (.model)", "mesh", ".model"

    # Cocos UI
    if head[:4] == b'CSB ' or head[:4] == b'FLAT':
        return "Cocos Studio UI (.csb)", "csb", ".csb"

    # Audio
    if head[:4] == b'RIFF':
        return "WAV Audio (.wav)", "audio", ".wav"
    if head[:4] == b'OggS':
        return "Ogg Audio (.ogg)", "audio", ".ogg"
    if head[:4] == b'BKHD':
        return "Wwise Soundbank (.bnk)", "audio", ".bnk"

    # Plaintext Check
    printable = sum(1 for b in head[:min(48, len(head))] if (32 <= b < 127 or b in (9, 10, 13)))
    if len(head) > 0 and (printable / min(48, len(head))) > 0.85:
        return "Text Config (.txt)", "text", ".txt"

    return "Binary Asset (.bin)", "binary", ".bin"

class NPKEntry:
    __slots__ = ('index', 'sig', 'offset', 'comp_len', 'orig_len', 'flags', 'detected_name', 'detected_type', 'category', 'ext', 'code_obj')
    def __init__(self, index, sig, offset, comp_len, orig_len, flags, d_type="Binary Asset", category="binary", ext=".bin"):
        self.index = index
        self.sig = sig
        self.offset = offset
        self.comp_len = comp_len
        self.orig_len = orig_len
        self.flags = flags
        self.detected_name = ""
        self.detected_type = d_type
        self.category = category
        self.ext = ext
        self.code_obj = None

class FastNPKArchive:
    def __init__(self, path):
        self.path = path
        self.file_size = os.path.getsize(path)
        self.file_obj = open(path, 'rb')
        self.mm = mmap.mmap(self.file_obj.fileno(), 0, access=mmap.ACCESS_READ)
        self.entries = []
        self.is_script_npk = False
        self._parse_headers()

    def _parse_headers(self):
        mm = self.mm
        if len(mm) < 28 or mm[:4] != b'NXPK':
            raise ValueError("Not a valid NetEase NeoX NXPK file!")
        
        cnt = struct.unpack_from('<I', mm, 4)[0]
        io_offset = struct.unpack_from('<I', mm, 0x14)[0]
        
        entries = []
        is_script = False

        for i in range(cnt):
            b = io_offset + i * 28
            if b + 28 > len(mm): break
            sig, off, ln, oln, f5, f6, f7 = struct.unpack_from('<IIIIIII', mm, b)
            
            d_type = "Binary Asset (.bin)"
            cat = "binary"
            ext = ".bin"

            if off + ln <= len(mm) and ln > 0:
                raw_chunk = mm[off:off + min(2048, ln)]
                
                if raw_chunk[:2] == b'\x7a\x1c':
                    d_type = "Python Script (.py)"
                    cat = "script"
                    ext = ".py"
                    is_script = True
                elif raw_chunk[:2] in (b'\x78\x9c', b'\x78\xda', b'\x78\x01'):
                    try:
                        decomp_head = zlib.decompressobj().decompress(raw_chunk, 128)
                        d_type, cat, ext = classify_header_data(decomp_head, raw_chunk)
                    except Exception:
                        d_type = "Compressed Data (.bin)"
                else:
                    d_type, cat, ext = classify_header_data(raw_chunk, raw_chunk)

            entries.append(NPKEntry(i, sig, off, ln, oln, (f5, f6, f7), d_type, cat, ext))

        self.entries = entries
        self.is_script_npk = is_script

    def read_raw_entry(self, entry):
        if entry.offset + entry.comp_len > len(self.mm): return b""
        return self.mm[entry.offset:entry.offset + entry.comp_len]

    def extract_entry(self, entry):
        raw = self.read_raw_entry(entry)
        if not raw: return b"", "empty", ""

        # Script Decryption
        if raw[:2] == b'\x7a\x1c':
            dec = decrypt_script_raw(raw)
            if dec:
                try:
                    co = PyUnmarshaller(dec).load()
                    fn = dec_str(co.get('file'))
                    entry.detected_name = fn
                    entry.code_obj = co
                    entry.detected_type = "Python Script (.py)"
                    entry.category = "script"
                    entry.ext = ".py"
                    return dec, "script", fn
                except Exception:
                    return dec, "script_raw", ""
        
        # Zlib Decompression
        if raw[:2] in (b'\x78\x9c', b'\x78\xda', b'\x78\x01'):
            try:
                decomp = zlib.decompress(raw)
                d_type, cat, ext = classify_header_data(decomp[:128], raw[:4])
                entry.detected_type = d_type
                entry.category = cat
                entry.ext = ext
                return decomp, cat, ""
            except Exception:
                pass

        d_type, cat, ext = classify_header_data(raw[:128], raw[:4])
        entry.detected_type = d_type
        entry.category = cat
        entry.ext = ext
        return raw, cat, ""

    def close(self):
        try: self.mm.close()
        except Exception: pass
        try: self.file_obj.close()
        except Exception: pass

# ---- Accurate NeoX 3D Model & Mesh Engine ----
class Accurate3DViewport:
    def __init__(self, canvas):
        self.canvas = canvas
        self.vertices = []     # (x, y, z) normalized
        self.triangles = []    # (i1, i2, i3)
        self.yaw = 1.0         # Default perspective angle for guns
        self.pitch = 0.25
        self.zoom = 1.0
        self.pan_x = 0
        self.pan_y = 0
        self.last_x = 0
        self.last_y = 0
        self.is_dragging = False
        self.is_panning = False
        self.auto_rotate = True
        self.render_mode = "Solid Shaded + Wireframe"

        self.canvas.bind("<ButtonPress-1>", self._on_mouse_down)
        self.canvas.bind("<B1-Motion>", self._on_mouse_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_mouse_up)
        self.canvas.bind("<ButtonPress-3>", self._on_pan_down)
        self.canvas.bind("<B3-Motion>", self._on_pan_drag)
        self.canvas.bind("<ButtonRelease-3>", self._on_pan_up)
        self.canvas.bind("<MouseWheel>", self._on_mouse_wheel)

    def load_neox_mesh(self, data):
        self.vertices = []
        self.triangles = []
        
        if len(data) < 36 or data[:4] != b'4\x80\xc8\xbb':
            self.redraw()
            return 0, 0

        try:
            vert_cnt = struct.unpack_from('<I', data, 16)[0]
        except Exception:
            vert_cnt = 0

        if vert_cnt < 3 or vert_cnt > 100000:
            self.redraw()
            return 0, 0

        # Auto-detect exact vertex stride
        stride = 24
        for test_stride in (24, 32, 28, 36, 40, 48, 12, 16):
            idx_offset = 36 + vert_cnt * test_stride
            if idx_offset + 20 <= len(data):
                valid_count = 0
                for k in range(min(20, (len(data) - idx_offset)//2)):
                    val = struct.unpack_from('<H', data, idx_offset + k*2)[0]
                    if val < vert_cnt: valid_count += 1
                    else: break
                if valid_count >= 15:
                    stride = test_stride
                    break

        # Read 3D Vertex Coordinates (X, Y, Z)
        raw_verts = []
        for i in range(vert_cnt):
            base = 36 + i * stride
            if base + 12 <= len(data):
                x, y, z = struct.unpack_from('<fff', data, base)
                if not (math.isnan(x) or math.isnan(y) or math.isnan(z)):
                    raw_verts.append((x, y, z))

        if not raw_verts:
            self.redraw()
            return 0, 0

        # Read Triangle Strip Index Buffer
        idx_base = 36 + vert_cnt * stride
        strip_indices = []
        for i in range(idx_base, len(data) - 2, 2):
            idx = struct.unpack_from('<H', data, i)[0]
            if idx < len(raw_verts):
                strip_indices.append(idx)
            else:
                break

        # Unpack Triangle Strip with Degenerate Triangles skip
        triangles = []
        for k in range(len(strip_indices) - 2):
            v1 = strip_indices[k]
            v2 = strip_indices[k + 1]
            v3 = strip_indices[k + 2]
            # Ignore degenerate reset triangles
            if v1 != v2 and v2 != v3 and v1 != v3:
                # Maintain consistent counter-clockwise polygon orientation
                if k % 2 == 0:
                    triangles.append((v1, v2, v3))
                else:
                    triangles.append((v1, v3, v2))

        # Center and Normalize Bounds
        min_x = min(p[0] for p in raw_verts); max_x = max(p[0] for p in raw_verts)
        min_y = min(p[1] for p in raw_verts); max_y = max(p[1] for p in raw_verts)
        min_z = min(p[2] for p in raw_verts); max_z = max(p[2] for p in raw_verts)

        cx = (min_x + max_x) / 2.0
        cy = (min_y + max_y) / 2.0
        cz = (min_z + max_z) / 2.0
        
        max_dim = max(max_x - min_x, max_y - min_y, max_z - min_z, 0.001)
        scale = 230.0 / max_dim

        self.vertices = [((p[0] - cx) * scale, (p[1] - cy) * scale, (p[2] - cz) * scale) for p in raw_verts]
        self.triangles = triangles
        self.zoom = 1.0
        self.pan_x = 0
        self.pan_y = 0
        self.yaw = 1.15
        self.pitch = 0.25
        self.redraw()
        return len(self.vertices), len(self.triangles)

    def _on_mouse_down(self, event):
        self.last_x = event.x
        self.last_y = event.y
        self.is_dragging = True
        self.auto_rotate = False

    def _on_mouse_drag(self, event):
        if not self.is_dragging: return
        dx = event.x - self.last_x
        dy = event.y - self.last_y
        self.yaw += dx * 0.012
        self.pitch += dy * 0.012
        self.last_x = event.x
        self.last_y = event.y
        self.redraw()

    def _on_mouse_up(self, event):
        self.is_dragging = False

    def _on_pan_down(self, event):
        self.last_x = event.x
        self.last_y = event.y
        self.is_panning = True
        self.auto_rotate = False

    def _on_pan_drag(self, event):
        if not self.is_panning: return
        self.pan_x += event.x - self.last_x
        self.pan_y += event.y - self.last_y
        self.last_x = event.x
        self.last_y = event.y
        self.redraw()

    def _on_pan_up(self, event):
        self.is_panning = False

    def _on_mouse_wheel(self, event):
        factor = 1.15 if event.delta > 0 else 0.85
        self.zoom = max(0.15, min(10.0, self.zoom * factor))
        self.redraw()

    def tick_auto_rotate(self):
        if self.auto_rotate and self.vertices:
            self.yaw += 0.018
            self.redraw()

    def redraw(self):
        canvas = self.canvas
        canvas.delete("all")
        
        cw = canvas.winfo_width() or 440
        ch = canvas.winfo_height() or 400
        cx = cw / 2.0 + self.pan_x
        cy = ch / 2.0 + self.pan_y

        # Draw 3D floor grid
        grid_color = "#181820"
        for i in range(-6, 7):
            p1 = self._project(i * 28, -90, -180, cx, cy)
            p2 = self._project(i * 28, -90, 180, cx, cy)
            if p1 and p2: canvas.create_line(p1[0], p1[1], p2[0], p2[1], fill=grid_color)
            
            p3 = self._project(-180, -90, i * 28, cx, cy)
            p4 = self._project(180, -90, i * 28, cx, cy)
            if p3 and p4: canvas.create_line(p3[0], p3[1], p4[0], p4[1], fill=grid_color)

        if not self.vertices:
            canvas.create_text(cx, cy, text="No 3D Model Data Selected", fill="#52525b", font=("Segoe UI", 13))
            return

        cos_y, sin_y = math.cos(self.yaw), math.sin(self.yaw)
        cos_p, sin_p = math.cos(self.pitch), math.sin(self.pitch)

        # 1. Transform all vertices
        transformed = []
        screen_pts = []
        dist = 450.0

        for x, y, z in self.vertices:
            # Yaw (Y)
            x1 = x * cos_y - z * sin_y
            z1 = x * sin_y + z * cos_y
            # Pitch (X)
            y2 = y * cos_p - z1 * sin_p
            z2 = y * sin_p + z1 * cos_p

            transformed.append((x1, y2, z2))
            
            fov = dist / (dist + z2 * 0.5) * self.zoom
            sx = cx + x1 * fov
            sy = cy - y2 * fov
            screen_pts.append((sx, sy, z2))

        # 2. Render Polygons / Triangles with Shading (Z-Buffer Depth Sort)
        if self.triangles and self.render_mode != "Point Cloud":
            lx, ly, lz = 0.577, 0.577, 0.577

            poly_draw_list = []
            for i1, i2, i3 in self.triangles:
                p1, p2, p3 = transformed[i1], transformed[i2], transformed[i3]
                s1, s2, s3 = screen_pts[i1], screen_pts[i2], screen_pts[i3]

                avg_z = (p1[2] + p2[2] + p3[2]) / 3.0

                # Surface Normal Calculation
                ax, ay, az = p2[0] - p1[0], p2[1] - p1[1], p2[2] - p1[2]
                bx, by, bz = p3[0] - p1[0], p3[1] - p1[1], p3[2] - p1[2]
                nx = ay * bz - az * by
                ny = az * bx - ax * bz
                nz = ax * by - ay * bx
                norm_len = math.sqrt(nx*nx + ny*ny + nz*nz) or 1.0
                nx /= norm_len; ny /= norm_len; nz /= norm_len

                # Diffuse Lambertian Lighting
                diffuse = max(0.18, min(1.0, (nx * lx + ny * ly + nz * lz) * 0.75 + 0.38))
                
                # Gun metallic cyan/blue shading
                r = int(12 * diffuse + 6)
                g = int(140 * diffuse + 25)
                b = int(225 * diffuse + 30)
                fill_color = f"#{r:02x}{g:02x}{b:02x}"
                edge_color = f"#{min(255, r+35):02x}{min(255, g+45):02x}{min(255, b+30):02x}"

                poly_draw_list.append((avg_z, s1[0], s1[1], s2[0], s2[1], s3[0], s3[1], fill_color, edge_color))

            # Painter's depth sorting
            poly_draw_list.sort(key=lambda t: t[0])

            # Draw Triangles on Canvas
            for item in poly_draw_list:
                z, x1, y1, x2, y2, x3, y3, fcolor, ecolor = item
                if self.render_mode == "Solid Shaded + Wireframe":
                    canvas.create_polygon(x1, y1, x2, y2, x3, y3, fill=fcolor, outline=ecolor, width=1)
                elif self.render_mode == "Wireframe Only":
                    canvas.create_polygon(x1, y1, x2, y2, x3, y3, fill="", outline="#38bdf8", width=1)

        else:
            for sx, sy, z2 in screen_pts:
                if 0 <= sx <= cw and 0 <= sy <= ch:
                    canvas.create_rectangle(sx-1, sy-1, sx+1, sy+1, fill="#38bdf8", outline="")

        canvas.create_text(
            15, 15,
            anchor="nw",
            text=f"🎮 3D Viewport: {len(self.vertices):,} Vertices | {len(self.triangles):,} Polygons | Zoom: {self.zoom:.2f}x\n(Left Drag: Orbit 360° | Right Drag: Pan | Scroll: Zoom)",
            fill="#cbd5e1",
            font=("Segoe UI", 9, "bold")
        )

    def _project(self, x, y, z, cx, cy):
        cos_y, sin_y = math.cos(self.yaw), math.sin(self.yaw)
        cos_p, sin_p = math.cos(self.pitch), math.sin(self.pitch)
        x1 = x * cos_y - z * sin_y
        z1 = x * sin_y + z * cos_y
        y2 = y * cos_p - z1 * sin_p
        z2 = y * sin_p + z1 * cos_p
        dist = 450.0
        fov = dist / (dist + z2 * 0.5) * self.zoom
        return cx + x1 * fov, cy - y2 * fov

# ---- Modern GUI Application ----
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

PAGE_SIZE = 400

class NPKStudioApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("RoS NeoX NPK Studio & Visual Asset Inspector (v5.0 Ultimate 3D)")
        self.geometry("1280x820")
        self.minsize(1020, 660)
        
        self.archive = None
        self.filtered_entries = []
        self.displayed_count = 0
        self.search_job = None
        self.current_pil_img = None
        self.tk_img = None
        
        self._build_ui()
        self._scan_default_paths()
        self._start_anim_loop()

    def _build_ui(self):
        # Header Toolbar
        self.top_frame = ctk.CTkFrame(self, height=52, corner_radius=0)
        self.top_frame.pack(fill="x")
        
        self.title_lbl = ctk.CTkLabel(
            self.top_frame,
            text="🎨 RoS NPK Asset Studio",
            font=ctk.CTkFont(size=18, weight="bold")
        )
        self.title_lbl.pack(side="left", padx=16, pady=8)

        self.btn_open = ctk.CTkButton(
            self.top_frame,
            text="📂 Open NPK...",
            command=self._on_open_file,
            width=120,
            height=32,
            font=ctk.CTkFont(size=12, weight="bold")
        )
        self.btn_open.pack(side="left", padx=6, pady=8)

        self.quick_label = ctk.CTkLabel(self.top_frame, text="Quick Select:", font=ctk.CTkFont(size=12))
        self.quick_label.pack(side="left", padx=(12, 4))

        self.quick_combo = ctk.CTkComboBox(
            self.top_frame,
            values=["(No NPKs detected)"],
            command=self._on_quick_select,
            width=220,
            height=30
        )
        self.quick_combo.pack(side="left", padx=4)

        self.btn_extract_all = ctk.CTkButton(
            self.top_frame,
            text="⚡ Extract All",
            fg_color="#238636",
            hover_color="#2ea043",
            command=self._on_extract_all,
            width=110,
            height=32,
            font=ctk.CTkFont(size=12, weight="bold")
        )
        self.btn_extract_all.pack(side="right", padx=16, pady=8)

        self.btn_extract_sel = ctk.CTkButton(
            self.top_frame,
            text="📥 Extract Selected",
            fg_color="#1f6feb",
            hover_color="#388bfd",
            command=self._on_extract_selected,
            width=125,
            height=32,
            font=ctk.CTkFont(size=12)
        )
        self.btn_extract_sel.pack(side="right", padx=6, pady=8)

        # Paned Work area
        self.main_paned = tk.PanedWindow(self, orient=tk.HORIZONTAL, bg="#18181b", bd=0, sashwidth=4)
        self.main_paned.pack(fill="both", expand=True, padx=8, pady=8)

        # Left Panel (Fast Table)
        self.left_frame = ctk.CTkFrame(self.main_paned, corner_radius=6)
        self.main_paned.add(self.left_frame, minsize=540)

        # Search & Filter bar
        self.search_frame = ctk.CTkFrame(self.left_frame, height=40, fg_color="transparent")
        self.search_frame.pack(fill="x", padx=8, pady=(8, 4))

        self.search_var = tk.StringVar()
        self.search_var.trace("w", self._on_search_typing)
        self.search_entry = ctk.CTkEntry(
            self.search_frame,
            placeholder_text="🔍 Instant search name, sig (0x...), type...",
            textvariable=self.search_var,
            height=28
        )
        self.search_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))

        self.filter_type_combo = ctk.CTkComboBox(
            self.search_frame,
            values=["All Types", "Textures / Images", "XML / Configs", "3D Meshes (.mesh)", "Skeleton Rigs (.rig)", "Python Scripts", "Audio", "Cocos UI", "Others"],
            command=lambda v: self._apply_filter(),
            width=155,
            height=28
        )
        self.filter_type_combo.set("All Types")
        self.filter_type_combo.pack(side="right")

        # Treeview / Table
        self.tree_frame = tk.Frame(self.left_frame, bg="#1e1e24")
        self.tree_frame.pack(fill="both", expand=True, padx=8, pady=(4, 8))

        columns = ("index", "sig", "name", "type", "size", "orig_size")
        self.tree = ttk.Treeview(self.tree_frame, columns=columns, show="headings", selectmode="extended")
        
        self.tree.heading("index", text="#", anchor="center")
        self.tree.heading("sig", text="Signature (Hex)", anchor="center")
        self.tree.heading("name", text="File / Target Name", anchor="w")
        self.tree.heading("type", text="Exact Asset Type", anchor="w")
        self.tree.heading("size", text="Comp. Size", anchor="e")
        self.tree.heading("orig_size", text="Decomp. Size", anchor="e")

        self.tree.column("index", width=50, stretch=False, anchor="center")
        self.tree.column("sig", width=105, stretch=False, anchor="center")
        self.tree.column("name", width=210, stretch=True, anchor="w")
        self.tree.column("type", width=180, stretch=False, anchor="w")
        self.tree.column("size", width=85, stretch=False, anchor="e")
        self.tree.column("orig_size", width=95, stretch=False, anchor="e")

        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Treeview",
                        background="#18181b",
                        foreground="#f4f4f5",
                        fieldbackground="#18181b",
                        rowheight=24,
                        font=("Segoe UI", 9))
        style.configure("Treeview.Heading",
                        background="#27272a",
                        foreground="#fafafa",
                        font=("Segoe UI", 9, "bold"),
                        relief="flat")
        style.map("Treeview",
                  background=[("selected", "#2563eb")],
                  foreground=[("selected", "#ffffff")])

        # Dark Theme Scrollbar Styling
        style.configure("Vertical.TScrollbar",
                        gripcount=0,
                        background="#3f3f46",
                        darkcolor="#18181b",
                        lightcolor="#18181b",
                        troughcolor="#18181b",
                        bordercolor="#18181b",
                        arrowcolor="#a1a1aa",
                        relief="flat")
        style.map("Vertical.TScrollbar",
                  background=[("pressed", "#71717a"), ("active", "#52525b"), ("!disabled", "#3f3f46")],
                  arrowcolor=[("pressed", "#ffffff"), ("active", "#ffffff"), ("!disabled", "#a1a1aa")])

        self.vsb = ttk.Scrollbar(self.tree_frame, orient="vertical", command=self._on_scroll_y, style="Vertical.TScrollbar")
        self.tree.configure(yscrollcommand=self._on_tree_yscroll)
        self.vsb.pack(side="right", fill="y")
        self.tree.pack(fill="both", expand=True)

        self.tree.bind("<<TreeviewSelect>>", self._on_tree_select)

        # Right Panel (Visual Inspector)
        self.right_frame = ctk.CTkFrame(self.main_paned, corner_radius=6)
        self.main_paned.add(self.right_frame, minsize=460)

        self.preview_title = ctk.CTkLabel(
            self.right_frame,
            text="✨ Visual Asset Inspector",
            font=ctk.CTkFont(size=14, weight="bold")
        )
        self.preview_title.pack(anchor="w", padx=12, pady=(10, 2))

        self.info_label = ctk.CTkLabel(
            self.right_frame,
            text="Click an asset in the table to preview it.",
            text_color="#a1a1aa",
            font=ctk.CTkFont(size=11)
        )
        self.info_label.pack(anchor="w", padx=12, pady=(0, 6))

        # Preview Tabs
        self.preview_tabs = ctk.CTkTabview(self.right_frame)
        self.preview_tabs.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        self.tab_mesh3d = self.preview_tabs.add("🎮 3D Model Viewport")
        self.tab_image = self.preview_tabs.add("🖼️ Texture / Image")
        self.tab_code = self.preview_tabs.add("📜 Code & Config")
        self.tab_hex = self.preview_tabs.add("🔍 Hex View")
        self.tab_info = self.preview_tabs.add("📋 Metadata")

        # 1. 3D Model Viewport Controls & Canvas
        self.mesh_top_bar = ctk.CTkFrame(self.tab_mesh3d, height=32, fg_color="transparent")
        self.mesh_top_bar.pack(fill="x", padx=4, pady=(2, 4))
        
        self.mesh_mode_combo = ctk.CTkComboBox(
            self.mesh_top_bar,
            values=["Solid Shaded + Wireframe", "Wireframe Only", "Point Cloud"],
            command=self._on_mesh_mode_change,
            width=180,
            height=24
        )
        self.mesh_mode_combo.set("Solid Shaded + Wireframe")
        self.mesh_mode_combo.pack(side="left", padx=2)

        self.btn_auto_rot = ctk.CTkButton(
            self.mesh_top_bar, text="🔄 Auto-Rotate", width=105, height=24,
            command=self._toggle_mesh_auto_rot
        )
        self.btn_auto_rot.pack(side="left", padx=6)

        self.btn_reset_view = ctk.CTkButton(
            self.mesh_top_bar, text="🎯 Reset View", width=95, height=24,
            fg_color="#334155", hover_color="#475569",
            command=self._reset_mesh_view
        )
        self.btn_reset_view.pack(side="left", padx=2)

        self.canvas_3d_frame = tk.Frame(self.tab_mesh3d, bg="#0b0b0e")
        self.canvas_3d_frame.pack(fill="both", expand=True, padx=4, pady=4)

        self.mesh_canvas = tk.Canvas(self.canvas_3d_frame, bg="#0b0b0e", bd=0, highlightthickness=0)
        self.mesh_canvas.pack(fill="both", expand=True)
        self.viewport_3d = Accurate3DViewport(self.mesh_canvas)

        # 2. Image / Texture Viewport
        self.img_info_lbl = ctk.CTkLabel(self.tab_image, text="", font=ctk.CTkFont(size=11, weight="bold"))
        self.img_info_lbl.pack(anchor="w", padx=8, pady=(4, 2))

        self.canvas_frame = tk.Frame(self.tab_image, bg="#121214")
        self.canvas_frame.pack(fill="both", expand=True, padx=4, pady=4)

        self.img_canvas = tk.Canvas(self.canvas_frame, bg="#121214", bd=0, highlightthickness=0)
        self.img_canvas.pack(fill="both", expand=True)

        # 3. Code / Config Viewer Tab
        self.code_text = ctk.CTkTextbox(self.tab_code, font=ctk.CTkFont(family="Consolas", size=11), wrap="none")
        self.code_text.pack(fill="both", expand=True, padx=4, pady=4)

        # 4. Hex View Tab
        self.hex_text = ctk.CTkTextbox(self.tab_hex, font=ctk.CTkFont(family="Consolas", size=10), wrap="none")
        self.hex_text.pack(fill="both", expand=True, padx=4, pady=4)

        # 5. Metadata Tab
        self.meta_text = ctk.CTkTextbox(self.tab_info, font=ctk.CTkFont(family="Segoe UI", size=11), wrap="word")
        self.meta_text.pack(fill="both", expand=True, padx=4, pady=4)

        # Status Bar
        self.status_bar = ctk.CTkFrame(self, height=28, corner_radius=0)
        self.status_bar.pack(fill="x", side="bottom")

        self.status_label = ctk.CTkLabel(
            self.status_bar,
            text="Ready. Select an NPK file.",
            font=ctk.CTkFont(size=11),
            text_color="#a1a1aa"
        )
        self.status_label.pack(side="left", padx=12)

        self.progress_bar = ctk.CTkProgressBar(self.status_bar, width=180)
        self.progress_bar.pack(side="right", padx=12)
        self.progress_bar.set(0)

    def _start_anim_loop(self):
        def loop():
            if hasattr(self, 'viewport_3d'):
                self.viewport_3d.tick_auto_rotate()
            self.after(30, loop)
        self.after(100, loop)

    def _toggle_mesh_auto_rot(self):
        if hasattr(self, 'viewport_3d'):
            self.viewport_3d.auto_rotate = not self.viewport_3d.auto_rotate

    def _reset_mesh_view(self):
        if hasattr(self, 'viewport_3d'):
            self.viewport_3d.yaw = 1.15
            self.viewport_3d.pitch = 0.25
            self.viewport_3d.zoom = 1.0
            self.viewport_3d.pan_x = 0
            self.viewport_3d.pan_y = 0
            self.viewport_3d.redraw()

    def _on_mesh_mode_change(self, mode):
        if hasattr(self, 'viewport_3d'):
            self.viewport_3d.render_mode = mode
            self.viewport_3d.redraw()

    def _scan_default_paths(self):
        found_npks = {}
        for d in [r"D:\Game\RosOfflineReborn", r"D:\Game\RosOfflineReborn\res"]:
            if os.path.exists(d):
                for f in os.listdir(d):
                    if f.lower().endswith(".npk"):
                        p = os.path.join(d, f)
                        rel = os.path.relpath(p, r"D:\Game\RosOfflineReborn")
                        found_npks[rel] = p
        
        self.found_npks = found_npks
        if found_npks:
            items = list(found_npks.keys())
            self.quick_combo.configure(values=items)
            default = "res\\weapon.npk" if "res\\weapon.npk" in items else ("script.npk" if "script.npk" in items else items[0])
            self.quick_combo.set(default)
            self._load_npk_file(found_npks[default])

    def _on_quick_select(self, choice):
        if hasattr(self, 'found_npks') and choice in self.found_npks:
            self._load_npk_file(self.found_npks[choice])

    def _on_open_file(self):
        path = filedialog.askopenfilename(
            title="Select NetEase NeoX .NPK File",
            filetypes=[("NPK Files", "*.npk"), ("All Files", "*.*")]
        )
        if path:
            self._load_npk_file(path)

    def _load_npk_file(self, path):
        if self.archive:
            self.archive.close()
        
        try:
            archive = FastNPKArchive(path)
            self.archive = archive
            self.status_label.configure(
                text=f"Loaded {os.path.basename(path)}: {len(archive.entries):,} files ({archive.file_size:,} bytes) - 100% Pre-Classified"
            )
            self.progress_bar.set(1.0)
            self._apply_filter()
        except Exception as e:
            self.status_label.configure(text=f"Error: {e}")
            messagebox.showerror("Error", str(e))

    def _on_search_typing(self, *args):
        if self.search_job:
            self.after_cancel(self.search_job)
        self.search_job = self.after(150, self._apply_filter)

    def _apply_filter(self):
        if not self.archive:
            return
        
        query = self.search_var.get().strip().lower()
        filter_type = self.filter_type_combo.get()

        for item in self.tree.get_children():
            self.tree.delete(item)

        filtered = []
        for entry in self.archive.entries:
            sig_hex = f"0x{entry.sig:08x}"
            name = entry.detected_name or f"file_{entry.sig:08x}"
            
            if filter_type == "Textures / Images" and entry.category != "image" and "Texture" not in entry.detected_type and "Image" not in entry.detected_type:
                continue
            elif filter_type == "XML / Configs" and entry.category != "text" and "XML" not in entry.detected_type and "JSON" not in entry.detected_type:
                continue
            elif filter_type == "3D Meshes (.mesh)" and entry.category != "mesh" and "Mesh" not in entry.detected_type:
                continue
            elif filter_type == "Skeleton Rigs (.rig)" and "Rig" not in entry.detected_type:
                continue
            elif filter_type == "Python Scripts" and entry.category != "script" and "Python" not in entry.detected_type:
                continue
            elif filter_type == "Audio" and entry.category != "audio" and "Audio" not in entry.detected_type:
                continue
            elif filter_type == "Cocos UI" and entry.category != "csb" and "Cocos" not in entry.detected_type:
                continue
            elif filter_type == "Others" and entry.category in ("image", "text", "mesh", "script", "audio", "csb", "rig"):
                continue

            if query:
                if not (query in name.lower() or query in sig_hex.lower() or query in str(entry.index) or query in entry.detected_type.lower()):
                    continue

            filtered.append(entry)

        self.filtered_entries = filtered
        self.displayed_count = 0
        self._load_more_items(PAGE_SIZE)

    def _load_more_items(self, count):
        start = self.displayed_count
        end = min(start + count, len(self.filtered_entries))
        
        for i in range(start, end):
            entry = self.filtered_entries[i]
            sig_hex = f"0x{entry.sig:08x}"
            name = entry.detected_name or f"file_{entry.sig:08x}"
            self.tree.insert(
                "",
                "end",
                iid=str(entry.index),
                values=(
                    entry.index,
                    sig_hex,
                    name,
                    entry.detected_type,
                    f"{entry.comp_len:,} B",
                    f"{entry.orig_len:,} B"
                )
            )
        
        self.displayed_count = end
        total = len(self.filtered_entries)
        showing = f"Showing {end:,} of {total:,}" if end < total else f"Showing all {total:,}"
        self.status_label.configure(text=f"{os.path.basename(self.archive.path)}: {showing} entries")

    def _on_scroll_y(self, *args):
        self.tree.yview(*args)

    def _on_tree_yscroll(self, first, last):
        self.vsb.set(first, last)
        if float(last) >= 0.95 and self.displayed_count < len(self.filtered_entries):
            self._load_more_items(PAGE_SIZE)

    def _on_tree_select(self, event):
        sel = self.tree.selection()
        if not sel: return
        
        idx = int(sel[0])
        entry = self.archive.entries[idx]
        
        sig_hex = f"0x{entry.sig:08x}"
        self.info_label.configure(text=f"Selected: #{entry.index} | Sig: {sig_hex} | {entry.detected_type}")
        
        data, cat, name = self.archive.extract_entry(entry)
        
        cur_row = list(self.tree.item(str(entry.index), 'values'))
        if cur_row[3] != entry.detected_type or (entry.detected_name and not cur_row[2].endswith(entry.detected_name)):
            cur_row[3] = entry.detected_type
            if entry.detected_name: cur_row[2] = entry.detected_name
            self.tree.item(str(entry.index), values=cur_row)

        # Update Metadata Tab
        meta_info = f"""=== ENTRY #{entry.index} METADATA ===
Signature Hash : {sig_hex} ({entry.sig})
File Offset    : 0x{entry.offset:08x} ({entry.offset:,} bytes)
Compressed Len : {entry.comp_len:,} bytes
Decomp. Len    : {len(data):,} bytes (Header: {entry.orig_len:,} bytes)
Detected Type  : {entry.detected_type}
Target Format  : {entry.ext}
Category       : {entry.category}
Archive File   : {self.archive.path}
"""
        self.meta_text.delete("1.0", "end")
        self.meta_text.insert("1.0", meta_info)

        # Hex View
        self.hex_text.delete("1.0", "end")
        hex_lines = []
        for i in range(0, min(512, len(data)), 16):
            chunk = data[i:i+16]
            hex_str = " ".join(f"{b:02X}" for b in chunk)
            ascii_str = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
            hex_lines.append(f"{i:06X}  {hex_str:<48}  |{ascii_str}|")
        if len(data) > 512:
            hex_lines.append(f"... ({len(data) - 512:,} more bytes)")
        self.hex_text.insert("1.0", "\n".join(hex_lines))

        # Clear image canvas
        self.img_canvas.delete("all")
        self.img_info_lbl.configure(text="")
        self.current_pil_img = None

        # 🎮 3D SOLID MODEL / MESH VIEWER
        if data[:4] == b'4\x80\xc8\xbb' or data[:4] == b'\x34\x80\xc8\xbb' or cat == "mesh" or "Mesh" in entry.detected_type:
            v_cnt, t_cnt = self.viewport_3d.load_neox_mesh(data)
            self.preview_tabs.set("🎮 3D Model Viewport")
            return

        # 🖼️ IMAGE / TEXTURE VIEWER
        if data[:4] == b'DDS ' or data[:8] == b'\x89PNG\r\n\x1a\n' or data[:3] == b'\xff\xd8\xff' or cat == "image":
            try:
                pil_img = Image.open(io.BytesIO(data))
                self.current_pil_img = pil_img
                w, h = pil_img.size
                fmt = pil_img.format or "DDS"
                mode = pil_img.mode
                self.img_info_lbl.configure(
                    text=f"🖼️ {fmt} Texture: {w} x {h} pixels | Mode: {mode} | Size: {len(data):,} bytes"
                )
                self._draw_image_on_canvas(pil_img)
                self.preview_tabs.set("🖼️ Texture / Image")
                return
            except Exception as ie:
                self.img_info_lbl.configure(text=f"Image decode error: {ie}")

        # 📜 PYTHON SCRIPT
        if entry.code_obj:
            co = entry.code_obj
            code_view = self._format_code_obj(co)
            self.code_text.delete("1.0", "end")
            self.code_text.insert("1.0", code_view)
            self.preview_tabs.set("📜 Code & Config")
            return

        # 📜 XML / JSON / TEXT CONFIG
        if data.startswith(b'\xef\xbb\xbf'):
            data_clean = data[3:]
        else:
            data_clean = data

        if data_clean[:5] in (b'<?xml', b'<NeoX', b'<Mate', b'<Enti', b'<Root', b'<Item', b'<Game', b'<Scen') or data_clean[:1] in (b'{', b'[') or cat == "text":
            try:
                text_str = data_clean.decode('utf-8')
            except Exception:
                try: text_str = data_clean.decode('latin1')
                except Exception: text_str = repr(data_clean[:2000])
            self.code_text.delete("1.0", "end")
            self.code_text.insert("1.0", text_str[:35000])
            self.preview_tabs.set("📜 Code & Config")
            return

        # Default fallback
        self.preview_tabs.set("🔍 Hex View")

    def _draw_image_on_canvas(self, pil_img):
        canvas = self.img_canvas
        canvas.delete("all")
        
        cw = canvas.winfo_width() or 420
        ch = canvas.winfo_height() or 380
        
        iw, ih = pil_img.size
        scale = min(cw / iw, ch / ih, 1.0)
        dw = max(1, int(iw * scale))
        dh = max(1, int(ih * scale))
        
        step = 16
        for y in range(0, ch, step):
            for x in range(0, cw, step):
                color = "#1a1a1e" if ((x // step + y // step) % 2 == 0) else "#222226"
                canvas.create_rectangle(x, y, x + step, y + step, fill=color, outline="")

        resized = pil_img.resize((dw, dh), Image.Resampling.LANCZOS)
        self.tk_img = ImageTk.PhotoImage(resized)
        
        px = (cw - dw) // 2
        py = (ch - dh) // 2
        canvas.create_image(px, py, anchor="nw", image=self.tk_img)

    def _format_code_obj(self, co, depth=0):
        if not isinstance(co, dict): return ""
        ind = "  " * depth
        nm = dec_str(co.get('name')) or '?'
        fn = dec_str(co.get('file')) or ''
        
        lines = []
        if depth == 0:
            lines.append(f"# SOURCE FILE: {fn}")
            lines.append(f"# MODULE: {nm}\n")
        
        lines.append(f"{ind}def {nm}():")
        varnames = [dec_str(v) for v in co.get('varnames', []) if v]
        if varnames:
            lines.append(f"{ind}    # Local Vars: {', '.join(varnames)}")

        names = [dec_str(n) for n in co.get('names', []) if n]
        if names:
            lines.append(f"{ind}    # Referenced Globals / Methods: {', '.join(names[:25])}")

        nested = [c for c in co.get('consts', []) if isinstance(c, dict) and 'code' in c]
        for child in nested:
            lines.append("")
            lines.append(self._format_code_obj(child, depth + 1))
        
        return "\n".join(lines)

    def _on_extract_selected(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("Select Entry", "Please select one or more entries in the table to extract.")
            return
        
        out_dir = filedialog.askdirectory(title="Select Destination Folder")
        if not out_dir: return

        entries = [self.archive.entries[int(i)] for i in sel]
        self._run_extraction(entries, out_dir)

    def _on_extract_all(self):
        if not self.archive:
            messagebox.showinfo("No Archive", "Please open an .npk file first.")
            return

        out_dir = filedialog.askdirectory(title="Select Destination Folder for All Files")
        if not out_dir: return

        self._run_extraction(self.archive.entries, out_dir)

    def _run_extraction(self, entries, out_dir):
        total = len(entries)
        self.btn_extract_all.configure(state="disabled")
        self.btn_extract_sel.configure(state="disabled")

        def worker():
            extracted_count = 0
            for i, entry in enumerate(entries):
                data, cat, name = self.archive.extract_entry(entry)
                
                if name:
                    clean_name = name.replace("\\", "/").replace(":", "")
                    if clean_name.startswith("/"): clean_name = clean_name[1:]
                    for prefix in ("d/h45na/pc_tmp/publish/script/", "publish/script/", "script/"):
                        if clean_name.lower().startswith(prefix):
                            clean_name = clean_name[len(prefix):]; break
                    rel_path = clean_name
                else:
                    rel_path = f"sig_{entry.sig:08x}{entry.ext}"

                dest_file = os.path.join(out_dir, rel_path)
                dest_dir = os.path.dirname(dest_file)
                if not os.path.exists(dest_dir):
                    os.makedirs(dest_dir, exist_ok=True)
                
                with open(dest_file, "wb") as f:
                    f.write(data)
                
                extracted_count += 1
                progress = (i + 1) / total
                if i % 25 == 0 or i == total - 1:
                    self.after(0, lambda p=progress, c=extracted_count: self._update_progress(p, c, total))

            self.after(0, lambda: self._on_extraction_complete(extracted_count, out_dir))

        threading.Thread(target=worker, daemon=True).start()

    def _update_progress(self, progress, count, total):
        self.progress_bar.set(progress)
        self.status_label.configure(text=f"Extracting... {count}/{total} files ({int(progress * 100)}%)")

    def _on_extraction_complete(self, count, out_dir):
        self.progress_bar.set(1.0)
        self.status_label.configure(text=f"Extraction finished! {count} files saved.")
        self.btn_extract_all.configure(state="normal")
        self.btn_extract_sel.configure(state="normal")
        
        res = messagebox.askyesno(
            "Extraction Finished",
            f"Successfully extracted {count:,} files to:\n{out_dir}\n\nDo you want to open the destination folder?"
        )
        if res:
            os.startfile(out_dir)

if __name__ == "__main__":
    app = NPKStudioApp()
    app.mainloop()
