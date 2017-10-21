import pyglet.sprite
import pyglet.resource
from pyglet import gl



class HUD:
    SPACING = 10

    def __init__(self, viewport):
        self.viewport = viewport
        self.batch = pyglet.graphics.Batch()

        image = pyglet.resource.image(f'hud.png')
        self.tiles = pyglet.image.ImageGrid(
            image=image,
            rows=4,
            columns=4,
        ).get_texture_sequence()


        self.weapons = []
        x = y = self.SPACING
        for t in range(5):
            ty, tx = divmod(t, 4)
            img = self.tiles[(3 - ty) * 4 + tx]

            sprite = pyglet.sprite.Sprite(
                img, x, y,
                batch=self.batch,
            )
            self.weapons.append(sprite)
            if t < 4:
                self.set_weapon_enabled(t, False)
            else:
                sprite.visible = False
            y += img.height + self.SPACING

        self.bars = pyglet.image.ImageGrid(
            image=image,
            rows=2,
            columns=4,
        ).get_texture_sequence()

    def set_weapon_visible(self, n, visible):
        self.weapons[n].visible = visible

    def set_weapon_enabled(self, n, enabled):
        w = self.weapons[n]
        if enabled:
            w.opacity = 255
        else:
            w.opacity = 64

    def set_boss_weapon(self, enabled):
        if enabled:
            color = (0, 80, 100)
        else:
            color = (255,) * 3

        for i in range(4):
            self.weapons[i].color = color

        self.weapons[4].visible = enabled

    def draw(self):
        self.batch.draw()
