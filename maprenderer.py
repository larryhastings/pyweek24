from math import floor, ceil

import pyglet.graphics
import pyglet.sprite
from pyglet import gl
from shader import Shader
import lightvolume

from json_map import get_texture_sequence


class Viewport:
    def __init__(self, w, h):
        self.w = w
        self.h = h
        self.pos = (0, 0)

    def bounds(self):
        """Return screen bounds as a tuple (l, r, b, t)."""
        w2 = self.w // 2
        h2 = self.h // 2
        x, y = self.pos
        return x - w2, x + w2, y - h2, y + h2

    def __enter__(self):
        gl.glPushMatrix()
        gl.glLoadIdentity()
        x, y = self.pos
        gl.glTranslatef(self.w // 2 - int(x), self.h // 2 - int(y), 0)

    def __exit__(self, *_):
        gl.glPopMatrix()


class Light:
    def __init__(self, pos=(0, 0), color=(1.0, 1.0, 1.0, 0.2)):
        self.pos = pos
        self.color = color


class MapRenderer:
    def __init__(self, tmxfile):
        self.lights = [Light((10, 10))]
        self.occluders = {}  # quick spatial hash of shadow casting tiles
        self.load(tmxfile)

    def load(self, tmxfile):
        """Populate a batch with sprites from the tmx file."""
        self.batch = pyglet.graphics.Batch()
        self.width = tmxfile.width
        self.height = tmxfile.height

        self.light_objects = []

        assert len(tmxfile.tilesets) == 1, "Multiple tilesets not supported."

        tileset = tmxfile.tilesets[0]
        filename = tileset.image.source
        self.tilew = tileset.tilewidth
        self.tileh = tileset.tileheight
        self.tiles_tex = get_texture_sequence(
            filename,
            self.tilew,
            self.tileh,
            tileset.margin,
            tileset.spacing
        )

        # Build mapping of tile texture by gid
        self.tiles = {}
        self.collision_gids = set()
        tileset.columns = 8  # FIXME: load from TMX
        rows = (tileset.tilecount + tileset.columns - 1) // tileset.columns
        tiles = iter(tileset.tiles)
        for y in range(rows):
            for x in range(tileset.columns):
                gid = x + y * tileset.columns + tileset.firstgid
                tex = self.tiles_tex[(rows - 1 - y), x]
                tex.anchor_x = 0  # tex.width // 2
                tex.anchor_y = 0  # tex.height // 2
                self.tiles[gid] = tex

                # Load which gids are collidable here
                tile = next(tiles, None)
                if tile:
                    props = {p.name: p.value for p in tile.properties}
                    if props.get('wall') == '1':
                        self.collision_gids.add(gid)

        self.sprites = {}
        for layernum, layer in enumerate(tmxfile.layers):
            for i, tile in enumerate(layer.tiles):
                if tile.gid == 0:
                    continue
                y, x = divmod(i, self.width)
                y = self.height - y - 1
                sprite = pyglet.sprite.Sprite(
                    self.tiles[tile.gid],
                    x=x * self.tilew,
                    y=y * self.tileh,
                    batch=self.batch,
                    usage="static"
                )
                if tile.gid in self.collision_gids:
                    self.occluders[x, y] = True
                self.sprites[x, y] = sprite

    def render(self):
        self.batch.draw()
        for light in self.lights:
            self.render_light(light)

    def render_light(self, light):
        occluders = []
        x, y = light.pos

        l = x - 5
        r = x + 5
        b = y - 5
        t = y + 5

        occluders.append(
            lightvolume.rect(
                l * self.tilew, r * self.tilew,
                b * self.tileh, t * self.tileh,
            )
        )

        for tx in range(int(floor(l)), int(ceil(r))):
            for ty in range(int(floor(b)), int(ceil(t))):
                if self.occluders.get((tx, ty)):
                    occluders.append(
                        lightvolume.rect(
                            tx * self.tilew, (tx + 1) * self.tilew,
                            ty * self.tileh, (ty + 1) * self.tileh
                        )
                    )
        wx = x * self.tilew
        wy = y * self.tileh
        gl.glColor4f(*light.color)
        lightvolume.draw_light((wx, wy), occluders)
        gl.glColor4f(1.0, 1.0, 1.0, 1.0)
