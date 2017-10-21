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

        self.bars = tuple(pyglet.image.ImageGrid(
            image=image,
            rows=2,
            columns=4,
        ).get_texture_sequence())[:2]

        self.power = tuple(
            pyglet.sprite.Sprite(
                bar,
                self.viewport.w - self.SPACING - bar.width,
                self.SPACING,
                batch=self.batch,
            )
            for bar in self.bars
        )
        self.power[0].opacity = 64

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

    def set_health(self, health):
        assert 0 <= health <= 1.0
        img = self.bars[1]
        sprite = self.power[1]

        top = 20 + health * 100
        region = img.get_region(0, 0, img.width, top)
        sprite.image = region

    def draw(self):
        self.batch.draw()
