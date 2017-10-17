import io
import math
import os
import pprint
import sys

# checked in, got from https://github.com/reidrac/pyglet-tiled-json-map.git
import json_map

# built from source, removed "inline" from Group_kill_p in */group.h
import lepton

# pip3.6 install pyglet
import pyglet.resource
import pyglet.window.key
import pymunk.pyglet_util

# pip3.6 install pymunk
# GAAH
tmp = sys.stdout
sys.stdout = io.StringIO()
import pymunk
sys.stdout = tmp
del tmp
from pymunk import Vec2d

# pip3.6 install tmx
import tmx

# pip3.6 install wasabi.geom
from wasabi.geom.vector import Vector, v
from wasabi.geom.vector import zero as vector_zero
from wasabi.geom.vector import unit_x as vector_unit_x
from wasabi.geom.vector import unit_y as vector_unit_y


key = pyglet.window.key
EVENT_HANDLED = pyglet.event.EVENT_HANDLED

window = pyglet.window.Window()

pyglet.resource.path = [".", "gfx/kenney_roguelike/Spritesheet"]
pyglet.resource.reindex()



def vector_clamp(v, other):
    """
    Clamp vector v so it's 
    """
    if other.x == 0:
        x = 0
    elif other.x < 0:
        x = max(v.x, other.x)
    else:
        x = min(v.x, other.x)

    if other.y == 0:
        y = 0
    elif other.y < 0:
        y = max(v.y, other.y)
    else:
        y = min(v.y, other.y)

    return Vector((x, y))



class Game:
    def __init__(self):
        self.paused = False

        self.pause_label = pyglet.text.Label('[Pause]',
                          font_name='Times New Roman',
                          font_size=64,
                          x=window.width//2, y=window.height//2,
                          anchor_x='center', anchor_y='center')

    def on_draw(self):
        if self.paused:
            self.pause_label.draw()

game = Game()


class Level:
    def __init__(self, basename):
        self.load(basename)

        self.map.set_viewport(0, 0, window.width, window.height)
        self.background_tiles, self.collision_tiles, self.player_position_tiles = (layer.tiles for layer in self.tiles.layers)
        self.upper_left = vector_zero
        self.lower_right = Vector((
            self.tiles.width * self.tiles.tilewidth,
            self.tiles.height * self.tiles.tileheight,
            ))

        self.foreground_sprite_group = pyglet.graphics.OrderedGroup(self.map.last_group + 1)
        self.construct_collision_geometry()
       

    def load(self, basename):
        # we should always save the tmx file
        # then export the json file
        # this function will detect that that's true
        json_path = basename + ".json"
        tmx_path = basename + ".tmx"
        try:
            json_stat = os.stat(json_path)
            tmx_stat = os.stat(tmx_path)
        except FileNotFoundError:
            sys.exit(f"Couldn't find both json and tmx for basename {basename}!")

        if tmx_stat.st_mtime >= json_stat.st_mtime:
            sys.exit(f"{json_path} map file out of date! Export JSON from {tmx_path}.")

        with pyglet.resource.file(json_path) as f:
            self.map = json_map.Map.load_json(f)

        self.tiles = tmx.TileMap.load(tmx_path)

        return self.map

    def construct_collision_geometry(self):
        x = 0
        y = 0

        # pass 1: RLE encode horizontal runs of tiles into rectangles
        in_rect = False
        startx = None
        rects = set()

        def finish_rect():
            nonlocal x
            nonlocal y
            nonlocal startx
            nonlocal in_rect
            in_rect = False
            # chimpunk coordinate space
            rect = ((startx, y), (x, y+self.tiles.tileheight))
            rects.add(rect)

        for y in range(0, self.tiles.height * self.tiles.tileheight, self.tiles.tileheight):
            for x in range(0, self.tiles.width * self.tiles.tilewidth, self.tiles.tilewidth):
                # we convert to tile coordinate space here
                tile = self.collision_tile_at(x, y)
                if tile:
                    if not in_rect:
                        in_rect = True
                        startx = x
                elif in_rect:
                    finish_rect()
            if in_rect:
                x += self.tiles.tilewidth
                finish_rect()

        # pass 2: merge rectangles down where possible
        # sort the rects so we find the top rect first
        # rects are now in chipmunk coordinate space
        final_rects = []
        sort_by_y = lambda box: (box[0][1], box[0][0])
        sorted_rects = list(reversed(sorted(rects, key=sort_by_y)))
        while sorted_rects:
            rect = sorted_rects.pop()
            if rect not in rects:
                continue
            start, end = rect
            start_x, start_y = start
            end_x, end_y = end
            new_start_y = start_y
            new_end_y = end_y
            while True:
                new_start_y += self.tiles.tileheight
                new_end_y += self.tiles.tileheight
                nextrect = ((start_x, new_start_y), (end_x, new_end_y))
                if nextrect not in rects:
                    break
                rects.remove(nextrect)
                end_y = new_end_y
            final_rects.append((Vec2d(start_x, start_y), Vec2d(end_x, end_y)))

        # final_rects.sort(key=sort_by_y)
        print("COLLISION RECTS")
        pprint.pprint(final_rects)

        self.space = pymunk.Space()
        self.draw_options = pymunk.pyglet_util.DrawOptions()
        self.space.gravity = (0, 0)

        # chipmunk coordinate space is *tile space*
        # not *pixels*
        # (if map is 100x100 tiles, then chipmunk is also 100x100, not 1600x1600)
        def add_body_from_bb(rect):
            start, end = rect
            width = end.x - start.x
            height = end.y - start.y
            center_x = start.x + (width >> 1)
            center_y = start.y + (height >> 1)

            body = pymunk.Body(body_type=pymunk.Body.STATIC)
            body.position = Vec2d(center_x, center_y)
            shape = pymunk.Poly.create_box(body, (width, height))
            self.space.add(body, shape)

        for rect in final_rects:
            add_body_from_bb(rect)

        upper_left = Vec2d(-50, -50)
        lower_right = Vec2d((self.tiles.width * self.tiles.tilewidth) + 50, (self.tiles.height * self.tiles.tileheight) + 50)

        # bounding boxes around level geometry to trap the player inside the level
        add_body_from_bb((upper_left, Vec2d(lower_right.x, 0)))
        add_body_from_bb((upper_left, Vec2d(0, lower_right.y)))
        add_body_from_bb((Vec2d(self.tiles.width * self.tiles.tilewidth, upper_left.y), lower_right))
        add_body_from_bb((Vec2d(upper_left.x, self.tiles.height * self.tiles.tileheight), lower_right))



    def on_draw(self):
        self.map.draw()

    def position_to_tile_index(self, x, y=None):
        if y is None:
            assert isinstance(x, Vector)
            y = x.y
            x = x.x
        index = int(((y // self.tiles.tileheight) * (self.tiles.width)) +
            (x // self.tiles.tilewidth))
        assert index < len(self.collision_tiles)
        return index

    def tile_index_to_position(self, index):
        y = (index // self.tiles.width)
        x = index - (y * self.tiles.width)
        y *= self.tiles.tileheight
        x *= self.tiles.tilewidth
        return Vector((x, y))

    def collision_tile_at(self, x, y=None):
        return self.collision_tiles[self.position_to_tile_index(x, y)].gid


level = Level("prototype")


sin_45degrees = math.sin(math.pi / 4)
vector_45degrees = Vector((sin_45degrees, sin_45degrees))


class Player:
    def __init__(self):
        # determine position based on first nonzero tile
        # found in player starting position layer
        for i, tile in enumerate(level.player_position_tiles):
            if tile.gid:
                # print("FOUND PLAYER TILE AT", i, level.tile_index_to_position(i))
                self.position = level.tile_index_to_position(i)
                break
        else:
            self.position = vector_zero
        # adjust player position
        # TODO why is this what we wanted?!
        self.position += Vector((0, level.tiles.tileheight))

        self.desired_speed = vector_zero
        self.normalized_desired_speed = vector_zero
        self.speed_multiplier = 100
        self.speed = vector_zero
        self.acceleration_frames = 20 # 20/60 of a second to get to full speed
        self.movement_keys = set()
        # coordinate system has (0, 0) at upper left
        self.movement_vectors = {
            key.UP:    vector_unit_y * -1,
            key.DOWN:  vector_unit_y,
            key.LEFT:  vector_unit_x * -1,
            key.RIGHT: vector_unit_x,
            }
        self.movement_opposites = {
            key.UP: key.DOWN,
            key.DOWN: key.UP,
            key.LEFT: key.RIGHT,
            key.RIGHT: key.LEFT
            }

        self.image = pyglet.image.load("player.png")
        self.sprite = pyglet.sprite.Sprite(self.image, batch=level.map.batch, group=level.foreground_sprite_group)

        self.body = pymunk.Body(mass=1, moment=pymunk.inf, body_type=pymunk.Body.DYNAMIC)
        self.body.position = Vec2d(self.position.x, self.position.y)
        self.body.velocity_func = self.on_update_velocity
        assert level.tiles.tileheight == level.tiles.tilewidth
        self.shape = pymunk.Circle(self.body, level.tiles.tilewidth / 2)
        level.space.add(self.body, self.shape)

        # self.control_body = pymunk.Body(mass=1, moment=pymunk.inf, body_type=pymunk.Body.DYNAMIC)
        # self.control_body.position = self.body.position
        # self.control_joint = pymunk.constraint.PivotJoint(self.control_body, self.body, (0, 0))
        # self.control_joint.max_bias = 200
        # self.control_joint.max_force = 3000
        # level.space.add(self.control_joint)

    def calculate_normalized_desired_speed(self):
        if not (self.desired_speed.x and self.desired_speed.y):
            self.normalized_desired_speed = self.desired_speed
        else:
            self.normalized_desired_speed = Vector((self.desired_speed.x * vector_45degrees.x, self.desired_speed.y * vector_45degrees.y))
        self.normalized_desired_speed *= self.speed_multiplier
        # print("normalized desired speed is now", self.normalized_desired_speed)

    def on_key_press(self, symbol, modifiers):
        if game.paused:
            return
        vector = self.movement_vectors.get(symbol)
        if not vector:
            return
        self.movement_keys.add(symbol)
        self.desired_speed += vector
        # if we press RIGHT while we're already pressing LEFT,
        # cancel out the LEFT (and ignore the keyup on it later)
        #
        # TODO:
        # press-and-hold right
        # then, press-and-hold left
        # then, release left
        # you should resume going right!
        opposite = self.movement_opposites[symbol]
        if opposite in self.movement_keys:
            opposite_vector = self.movement_vectors[opposite]
            self.desired_speed -= opposite_vector
            self.movement_keys.remove(opposite)
        self.calculate_normalized_desired_speed()
        return pyglet.event.EVENT_HANDLED

    def on_key_release(self, symbol, modifiers):
        if game.paused:
            return
        vector = self.movement_vectors.get(symbol)
        if not vector:
            return
        if symbol in self.movement_keys:
            self.movement_keys.remove(symbol)
            vector = self.movement_vectors.get(symbol)
            self.desired_speed -= vector
            self.calculate_normalized_desired_speed()
        return pyglet.event.EVENT_HANDLED

    def on_player_move(self):
        p = Vec2d(self.body.position.x,
            self.body.position.y)
        self.sprite.position = (p.x, window.height - p.y - 1)
        # self.sprite.x = self.position.x
        # self.sprite.y = window.height - self.position.y - 1
        level.map.set_focus(p.x, p.y)

    def on_update_velocity(self, body, gravity, damping, dt):
        velocity = Vec2d(self.speed.x, self.speed.y) * 3
        body.velocity = velocity
        self.body.velocity = velocity

    def on_update(self, dt):
        # TODO
        # actually use dt here
        # instead of assuming it's 1/60 of a second
        # print("PLAYER UPDATE", self.speed, self.normalized_desired_speed)
        if self.speed != self.normalized_desired_speed:
            delta = self.normalized_desired_speed / self.acceleration_frames
            self.speed += delta
            self.speed = vector_clamp(self.speed, self.normalized_desired_speed)
            # print("SPEED IS NOW", self.speed)
        velocity = Vec2d(self.speed.x, self.speed.y)
        # self.control_body.position = self.body.position + velocity
        if 0:
            if self.speed:
                new_position = self.position + self.speed
                x, y = new_position
                if x < level.upper_left.x:
                    x = level.upper_left.x
                if y < level.upper_left.y:
                    y = level.upper_left.y
                if x > level.lower_right.x:
                    x = level.lower_right.x
                if y > level.lower_right.y:
                    y = level.lower_right.y
                # now check if we're colliding
                for key in self.movement_keys:
                    vector = self.movement_vectors[key] * 8
                    tile_position = new_position + vector
                    if level.collision_tile_at(tile_position):
                        # throw away movement in bad direction
                        if vector.x:
                            x = self.position.x
                        else:
                            y = self.position.y
                # print("new position", new_position)
                new_position = Vector((x, y))
                if self.position != new_position:
                    self.position = new_position
                    # print("position now", self.position)


    def on_draw(self):
        self.on_player_move()
        # we're actually drawn as part of the batch for the tiles
        pass


player = Player()
player.on_player_move()



keypress_handlers = {}
def keypress(key):
    def wrapper(fn):
        keypress_handlers[key] = fn
        return fn
    return wrapper


@keypress(key.ESCAPE)
def key_escape(pressed):
    # print("ESC", pressed)
    pyglet.app.exit()

@keypress(key.SPACE)
def key_escape(pressed):
    # print("SPACE", pressed)
    if pressed:
        game.paused = not game.paused

@keypress(key.UP)
def key_up(pressed):
    print("UP", pressed)

@keypress(key.DOWN)
def key_down(pressed):
    print("DOWN", pressed)

@keypress(key.LEFT)
def key_left(pressed):
    print("LEFT", pressed)

@keypress(key.RIGHT)
def key_right(pressed):
    print("RIGHT", pressed)


@keypress(key.LCTRL)
def key_lctrl(pressed):
    print("LEFT CONTROL", pressed)


key_remapper = {
    key.W: key.UP,
    key.S: key.DOWN,
    key.A: key.LEFT,
    key.D: key.RIGHT,
    }


@window.event
def on_key_press(symbol, modifiers):
    # ignoring modifiers for now
    symbol = key_remapper.get(symbol, symbol)
    # calling it manually instead of stacking
    # so we can benefit from remapped keys
    if player.on_key_press(symbol, modifiers) == EVENT_HANDLED:
        return
    handler = keypress_handlers.get(symbol)
    if handler:
        handler(True)
        return EVENT_HANDLED

@window.event
def on_key_release(symbol, modifiers):
    # ignoring modifiers for now
    symbol = key_remapper.get(symbol, symbol)
    # calling it manually instead of stacking
    # so we can benefit from remapped keys
    if player.on_key_release(symbol, modifiers) == EVENT_HANDLED:
        return
    handler = keypress_handlers.get(symbol)
    if handler:
        handler(False)
        return EVENT_HANDLED


@window.event
def on_draw():
    window.clear()
    level.on_draw()
    player.on_draw()
    game.on_draw()
    fire_on_draw()



def on_update(dt):
    player.on_update(dt)
    level.space.step(dt)

pyglet.clock.schedule_interval(on_update, 1/60.0)

# fireworks
import os
import math
from random import expovariate, uniform, gauss
from pyglet import image
from pyglet.gl import *

from lepton import Particle, ParticleGroup, default_system, domain
from lepton.renderer import PointRenderer
from lepton.texturizer import SpriteTexturizer, create_point_texture
from lepton.emitter import StaticEmitter, PerParticleEmitter
from lepton.controller import Gravity, Lifetime, Movement, Fader, ColorBlender

spark_tex = image.load(os.path.join(os.path.dirname(__file__), 'flare3.png')).get_texture()
spark_texturizer = SpriteTexturizer(spark_tex.id)
trail_texturizer = SpriteTexturizer(create_point_texture(8, 50))


class Kaboom:
    lifetime = 5

    def __init__(self, pos):
        color=(uniform(0,1), uniform(0,1), uniform(0,1), 1)
        while max(color[:3]) < 0.9:
            color=(uniform(0,1), uniform(0,1), uniform(0,1), 1)

        x, y = pos

        spark_emitter = StaticEmitter(
            template=Particle(
                position=(uniform(x - 5, x + 5), uniform(y - 5, y + 5), 0),
                color=color),
            deviation=Particle(
                velocity=(gauss(0, 5), gauss(0, 5), 0),
                age=1.5),
            velocity=domain.Sphere((0, gauss(40, 20), 0), 60, 60))

        self.sparks = ParticleGroup(
            controllers=[
                Lifetime(self.lifetime * 0.75),
                Movement(damping=0.93),
                ColorBlender([(0, (1,1,1,1)), (2, color), (self.lifetime, color)]),
                Fader(fade_out_start=1.0, fade_out_end=self.lifetime * 0.5),
            ],
            renderer=PointRenderer(abs(gauss(10, 3)), spark_texturizer))

        spark_emitter.emit(int(gauss(60, 40)) + 50, self.sparks)

        spread = abs(gauss(0.4, 1.0))
        self.trail_emitter = PerParticleEmitter(self.sparks, rate=uniform(5,30),
            template=Particle(
                color=color),
            deviation=Particle(
                velocity=(spread, spread, spread),
                age=self.lifetime * 0.75))

        self.trails = ParticleGroup(
            controllers=[
                Lifetime(self.lifetime * 1.5),
                Movement(damping=0.83),
                ColorBlender([(0, (1,1,1,1)), (1, color), (self.lifetime, color)]),
                Fader(max_alpha=0.75, fade_out_start=0, fade_out_end=gauss(self.lifetime, self.lifetime*0.3)),
                self.trail_emitter
            ],
            renderer=PointRenderer(10, trail_texturizer))

        pyglet.clock.schedule_once(self.die, self.lifetime * 2)

    def reduce_trail(self, dt=None):
        if self.trail_emitter.rate > 0:
            self.trail_emitter.rate -= 1

    def die(self, dt=None):
        default_system.remove_group(self.sparks)
        default_system.remove_group(self.trails)

# win = pyglet.window.Window(resizable=True, visible=False)
# win.clear()

def on_resize(width, height):
    """Setup 3D projection for window"""
    glViewport(0, 0, width, height)
    glMatrixMode(GL_PROJECTION)
    glLoadIdentity()
    gluPerspective(70, 1.0*width/height, 0.1, 1000.0)
    glMatrixMode(GL_MODELVIEW)
    glLoadIdentity()
# window.on_resize = on_resize

yrot = 0.0


glEnable(GL_BLEND)
glShadeModel(GL_SMOOTH)
glBlendFunc(GL_SRC_ALPHA,GL_ONE)
glHint(GL_PERSPECTIVE_CORRECTION_HINT,GL_NICEST);
glDisable(GL_DEPTH_TEST)

default_system.add_global_controller(
    Gravity((0,-15,0))
)

MEAN_FIRE_INTERVAL = 3.0

def fire(dt=None):
    x = player.position.x
    y = window.height - player.position.y - 1
    Kaboom((x, y))
    pyglet.clock.schedule_once(fire, expovariate(1.0 / (MEAN_FIRE_INTERVAL - 1)) + 1)


fire()
pyglet.clock.schedule_interval(default_system.update, (1.0/30.0))
pyglet.clock.set_fps_limit(None)


def fire_on_draw():
    global yrot
    with level.map:
        default_system.draw()
        # level.space.debug_draw(level.draw_options)
    '''
    glBindTexture(GL_TEXTURE_2D, 1)
    glEnable(GL_TEXTURE_2D)
    glEnable(GL_POINT_SPRITE)
    glPointSize(100);
    glBegin(GL_POINTS)
    glVertex2f(0,0)
    glEnd()
    glBindTexture(GL_TEXTURE_2D, 2)
    glEnable(GL_TEXTURE_2D)
    glEnable(GL_POINT_SPRITE)
    glPointSize(100);
    glBegin(GL_POINTS)
    glVertex2f(50,0)
    glEnd()
    glBindTexture(GL_TEXTURE_2D, 0)
    '''


pyglet.app.run()
