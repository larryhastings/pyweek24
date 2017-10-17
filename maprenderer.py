import pyglet.graphics
import pyglet.sprite
from pyglet import gl
from shader import Shader

from json_map import get_texture_sequence


class Viewport:
    def __init__(self, w, h):
        self.w = w
        self.h = h
        self.pos = (0, 0)

    def __enter__(self):
        gl.glPushMatrix()
        x, y = self.pos
        gl.glTranslatef(self.w // 2 - int(x), self.h // 2 - int(y), 0)

    def __exit__(self, *_):
        gl.glPopMatrix()


class MapRenderer:
    def __init__(self, tmxfile):
        self.light = 10, 10
        self.load(tmxfile)

    def load(self, tmxfile):
        self.batch = pyglet.graphics.Batch()
        self.width = tmxfile.width
        self.height = tmxfile.height

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
        rows = (tileset.tilecount + tileset.columns - 1) // tileset.columns
        for y in range(rows):
            for x in range(tileset.columns):
                gid = x + y * tileset.columns + tileset.firstgid
                tex = self.tiles_tex[(rows - 1 - y), x]
                self.tiles[gid] = tex

        self.sprites = {}
        for layer in tmxfile.layers:
            for i, tile in enumerate(layer.tiles):
                if tile.gid == 0:
                    continue
                y, x = divmod(i, self.width)
                sprite = pyglet.sprite.Sprite(
                    self.tiles[tile.gid],
                    x=x * self.tilew,
                    y=self.height - y * self.tileh,
                    batch=self.batch,
                    usage="static"
                )
                self.sprites[x, y] = sprite

    def render(self):
        self.batch.draw()
