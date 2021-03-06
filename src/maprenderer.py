import os.path
from math import degrees

import pyglet.graphics
import pyglet.sprite
from pyglet import gl
import tmx

from json_map import get_texture_sequence
from lighting import Light


class Viewport:
    def __init__(self, w, h):
        self.w = w
        self.h = h
        self.position = (0, 0)
        self.angle = 0

        self.vl = pyglet.graphics.vertex_list(
            4,
            ('v2f/static', (0, 0, 1, 0, 1, 1, 0, 1)),
            ('t2f/static', (0, 0, 1, 0, 1, 1, 0, 1))
        )

    def bounds(self):
        """Return screen bounds as a tuple (l, r, b, t)."""
        w2 = self.w // 2
        h2 = self.h // 2
        x, y = self.position
        return x - w2, x + w2, y - h2, y + h2

    def draw_quad(self):
        """Draw a full-screen quad."""
        gl.glPushMatrix()
        gl.glLoadIdentity()
        gl.glScalef(self.w, self.h, 1.0)
        self.vl.draw(gl.GL_QUADS)
        gl.glPopMatrix()

    def __enter__(self):
        gl.glPushMatrix()
        gl.glLoadIdentity()
        x, y = self.position
        gl.glTranslatef(self.w // 2, self.h // 2, 0)
        gl.glRotatef(degrees(self.angle), 0, 0, -1)
        gl.glTranslatef(-int(x), -int(y), 0)

    def __exit__(self, *_):
        gl.glPopMatrix()


class MapRenderer:
    def __init__(self, tmxfile):
        self.shadow_casters = {}  # quick spatial hash of shadow casting tiles
        self.load(tmxfile)

    def load(self, tmxfile):
        """Populate a batch with sprites from the tmx file."""
        self.batch = pyglet.graphics.Batch()
        self.width = tmxfile.width
        self.height = tmxfile.height

        self.light_objects = []

        tileset = [t for t in tmxfile.tilesets if 'object' not in t.name.lower()][0]
        filename = tileset.image.source
        self.tilew = tileset.tilewidth
        self.tileh = tileset.tileheight
        self.tiles_tex = get_texture_sequence(
            os.path.basename(filename),
            self.tilew,
            self.tileh,
            tileset.margin,
            tileset.spacing
        )

        # Build mapping of tile texture by gid
        self.tiles = {}
        self.light_tiles = {}
        self.collision_gids = set()
        self.collision_tiles = {}

        rows = (tileset.tilecount + tileset.columns - 1) // tileset.columns

        for tile in tileset.tiles:
            y, x = divmod(tile.id, tileset.columns)
            gid = tileset.firstgid + tile.id
            tex = self.tiles_tex[(rows - 1 - y), x]
            tex.anchor_x = 0  # tex.width // 2
            tex.anchor_y = 0  # tex.height // 2
            self.tiles[gid] = tex

            # Load which gids are collidable here
            props = {p.name: p.value for p in tile.properties}
            wall = int(props.get('wall', '0'))
            if wall:
                self.collision_gids.add(gid)
                self.collision_tiles[gid] = int(wall)

            if 'lightx' in props:
                lightx = props['lightx']
                lighty = props['lighty']
                self.light_tiles[gid] = lightx, lighty

        tile_layers = [l for l in tmxfile.layers if isinstance(l, tmx.Layer)]
        self.sprites = {}

        tile_map = bytearray()
        verts = []
        tcs = []
        epsilon = 0
        for layernum, layer in enumerate(tile_layers):
            for i, tile in enumerate(layer.tiles):
                if tile.gid == 0:
                    continue
                y, x = divmod(i, self.width)
                y = self.height - y - 1

                tex = self.tiles[tile.gid]

                l = x * self.tilew - epsilon
                t = y * self.tileh - epsilon
                r = l + self.tilew + epsilon
                b = t + self.tileh + epsilon

                #verts.extend([l, b, l, t, r, t, r, b])
                verts.extend([l, t, r, t, r, b, l, b, ])
                # verts.extend([l, b, r, b, r, t, l, t])
                tcs.extend(
                    c for i, c in enumerate(tex.tex_coords) if i % 3 != 2
                )

                gid = tile.gid
                if gid in self.collision_tiles:
                    wall = self.collision_tiles[gid]
                    self.shadow_casters[x, y] = wall

                light = self.light_tiles.get(gid)
                if light:
                    lx, ly = light
                    self.light_objects.append(
                        Light((lx + x, ly + y))
                    )

        self.group = pyglet.sprite.SpriteGroup(
            self.tiles_tex.get_texture(),
            gl.GL_SRC_ALPHA, gl.GL_ONE_MINUS_SRC_ALPHA
            #gl.GL_ONE, gl.GL_ZERO
        )
        self.vl = self.batch.add(
            len(verts) // 2,
            gl.GL_QUADS,
            self.group,
            ('v2i/static', verts),
            ('t2f/static', tcs),
        )

    def render(self):
        self.batch.draw()

