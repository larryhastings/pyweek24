#!/usr/bin/env python3

# system includes
from enum import Enum, IntEnum
import io
import math
from math import floor, atan2, degrees
import os
import pprint
import random
import sys
import operator

# built from source
from lepton import default_system

# pip3.6 install pyglet
# currently 1.2.4
import pyglet.resource
import pyglet.media
import pyglet.window.key
from pyglet import gl

pyglet.options['audio'] = ('openal', 'directsound', 'silent')
pyglet.resource.path = ["gfx", "fonts", "sfx"]
pyglet.resource.reindex()


# pip3.6 install pymunk
# currently version 5.3.2
#
# GAAH, prevent pymunk from printing to stdout on import
tmp = sys.stdout
sys.stdout = io.StringIO()
import pymunk
sys.stdout = tmp
del tmp
import pymunk.pyglet_util

# Vec2D: 2D vector, mutable (sigh)
from pymunk import Vec2d
vector_zero = Vec2d.zero()
vector_unit_x = Vec2d(1, 0)
vector_unit_y = Vec2d(0, 1)

# pip3.6 install tmx
# currently 1.9.1
import tmx

# local libraries
from particles import Trail, Kaboom, Smoke, diffuse_system, Impact
from maprenderer import MapRenderer, Viewport
from lighting import LightRenderer, Light
from hud import HUD


key = pyglet.window.key
EVENT_HANDLED = pyglet.event.EVENT_HANDLED

window = pyglet.window.Window(600, 800)
window.set_exclusive_mouse(True)
window.set_caption("My Sincerest Apologies")
window.set_icon(pyglet.image.load('gfx/icon32.png'), pyglet.image.load('gfx/icon16.png'))



viewport = Viewport(*window.get_size())
debug_viewport = Viewport(50, 50)

ENGINE_TICKS_IN_HERTZ = 120

PLAYER_GLOW = (0, 0.4, 0.5)

lighting = LightRenderer(viewport)


impact_sound = pyglet.resource.media('impact.wav', streaming=False)
rail_sound = pyglet.resource.media('rail.wav', streaming=False)
default_sound = laser_sound = pyglet.resource.media('laser.wav', streaming=False)
laser2_sound = pyglet.resource.media('laser2.wav', streaming=False)
bkill_sound = pyglet.resource.media('boss_killer.wav', streaming=False)



music_player = None


def play_music(filename):
    global music_player
    if music_player:
        music_player.delete()
    music_player = pyglet.resource.media(filename).play()
    music_player.on_eos = lambda: play_music(filename)


play_music('bensound-scifi.mp3')


def _clamp(c, other):
    if other == 0:
        return 0
    negate = -1 if c < 0 else 1
    c = abs(c)
    other = abs(other)
    if c > other:
        return other * negate
    return c * negate

def vector_clamp(v, other):
    """
    Clamp vector v so it doesn't extend further than "other".
    Return a new vector.
    """
    return Vec2d(_clamp(v.x, other.x), _clamp(v.y, other.y))


class CollisionType(IntEnum):
    INVALID = 0
    WALL = 1
    PLAYER = 2
    PLAYER_BULLET = 4
    ROBOT = 8
    ROBOT_BULLET = 16



class RobotSprite:
    """Base class for a robot sprite.

    There is some Pyglet magic here that is intended to allow the same
    sprites to be re-rendered with different textures in different phases
    of the draw pipeline. This allows robots to have lights that are not
    shadowed.

    """

    ROWS = COLS = 8
    FILENAMES = 'obj_s'

    batch = pyglet.graphics.Batch()

    flips = {}

    @classmethod
    def load(cls):
        cls.diffuse_tex = pyglet.resource.texture(f'{cls.FILENAMES}_diffuse.png')
        cls.emit_tex = pyglet.resource.texture(f'{cls.FILENAMES}_emit.png')
        cls.flip_tex = pyglet.image.Texture(
            cls.diffuse_tex.width,
            cls.diffuse_tex.height,
            gl.GL_TEXTURE_2D,
            cls.diffuse_tex.id
        )

        cls.flips[cls.flip_tex.id] = (cls.diffuse_tex, cls.emit_tex)

        cls.grid = pyglet.image.ImageGrid(
            image=cls.flip_tex,
            rows=cls.ROWS,
            columns=cls.COLS,
        )
        cls.sprites = {}
        for i, img in enumerate(cls.grid.get_texture_sequence()):
            y, x = divmod(i, cls.COLS)
            y = cls.ROWS - y - 1
            img.anchor_x = img.width / 2
            img.anchor_y = img.height / 2
            cls.sprites[x, y] = img

    @classmethod
    def draw_diffuse(cls):
        cls.batch.draw()

    @classmethod
    def draw_emit(cls):
        revert = []
        for group in cls.batch.top_groups:
            diff, emit = cls.flips[group.texture.id]
            group.texture = emit
            group.blend_dest = gl.GL_ONE
            revert.append((group, diff))
        cls.batch.draw()
        for group, diff in revert:
            group.texture = diff
            group.blend_dest = gl.GL_ONE_MINUS_SRC_ALPHA

    def __init__(self, position, sprite_position, angle=0):
        self.sprite = pyglet.sprite.Sprite(
            self.sprites[tuple(sprite_position)],
            batch=self.batch
        )
        self.angle = angle
        self.position = position

    @property
    def visible(self):
        return self.sprite.visible

    @visible.setter
    def visible(self, v):
        self.sprite.visible = v

    @property
    def position(self):
        return self.sprite.position

    @position.setter
    def position(self, v):
        x, y = v
        self.sprite.position = floor(x + 0.5), floor(y + 0.5)

    @property
    def angle(self):
        """Angle of the sprite in radians."""
        return math.radians(-self.sprite.rotation)

    @angle.setter
    def angle(self, v):
        """Set the angle of the sprite."""
        self.sprite.rotation = -math.degrees(v)

    def delete(self):
        self.sprite.delete()



class PlayerRobotSprite(RobotSprite):
    """Player robot."""

    MIN = 0
    MAX = 3

    ROW = 0

    def __init__(self, position, level=0):
        super().__init__(position, (0, 0))
        self.level = level

    @property
    def level(self):
        return self._level

    @level.setter
    def level(self, v):
        if not (self.MIN <= v <= self.MAX):
            raise ValueError(
                f'{type(self).__name__}.level must be '
                f'{self.MIN}-{self.MAX} (not {v})'
            )
        self._level = v
        self.sprite.image = self.sprites[self._level, self.ROW + (v + 1) % 2]


class EnemyRobotSprite(PlayerRobotSprite):
    """Sprites for the enemies."""
    ROW = 2


class BigSprite(RobotSprite):
    ROWS = COLS = 4
    FILENAMES = 'obj_l'

    SPRITE = 0, 0


class WideSprite(RobotSprite):
    ROWS = 8
    COLS = 4
    FILENAMES = 'obj_w'


OBJECT_TYPES = {}


def big_object(cls):
    """Register a class as implementing a big object loaded from level data."""
    OBJECT_TYPES[cls.__name__] = cls
    return cls


class BigRobotSprite(BigSprite):
    def __init__(self, position, angle=0):
        super().__init__(position, self.SPRITE, angle=angle)


@big_object
class Fab(BigRobotSprite):
    SPRITE = 0, 0

    def __init__(self, position, angle=0):
        super().__init__(position, angle=angle)

        self.body = pymunk.Body(mass=pymunk.inf, moment=pymunk.inf, body_type=pymunk.Body.STATIC)
        self.body.position = Vec2d(level.world_to_map(self.position))
        shape = pymunk.Poly.create_box(self.body, (2, 2))
        shape.collision_type = CollisionType.WALL
        level.space.add(shape)
        level.space.add(self.body)
        level.start_position = level.world_to_map(position + Vec2d(0, -64))

        global hud
        global player
        global reticle

        assert hud is None
        assert player is None
        assert reticle is None

        reticle = Reticle()

        player = Player()
        player.on_player_moved()
        hud = HUD(viewport)


@big_object
class Crate(RobotSprite):
    SPRITE = 5, 2

    def __init__(self, position, angle=0):
        super().__init__(position, self.SPRITE, angle=angle)

        self.body = pymunk.Body(mass=20, moment=10, body_type=pymunk.Body.DYNAMIC)
        self.body.position = Vec2d(level.world_to_map(self.position))
        self.shape = pymunk.Poly.create_box(self.body, (1, 1))
        self.shape.collision_type = CollisionType.WALL
        level.space.add(self.body, self.shape)
        pyglet.clock.schedule(self.update)

    def update(self, dt):
        self.position = level.map_to_world(self.body.position)
        self.angle = self.body.angle
        self.body.angular_velocity *= 0.05 ** dt
        self.body.velocity *= 0.05 ** dt

    def delete(self):
        level.space.remove(self.body, self.shape)
        super().delete()


class Destroyable(WideSprite):
    """Things that can be destroyed."""
    def __init__(self, position, angle=0):
        super().__init__(position, self.SPRITE, angle=angle)
        self.create_body()
        self.scalev = 0

    def create_body(self):
        self.body = pymunk.Body(mass=pymunk.inf, moment=pymunk.inf, body_type=pymunk.Body.STATIC)
        self.body.position = Vec2d(level.world_to_map(self.position))
        self.body.angle = self.angle
        self.shape = pymunk.Poly.create_box(self.body, (2, 1))
        self.shape.collision_type = CollisionType.ROBOT
        level.space.add(self.body, self.shape)
        shape_to_robot[self.shape] = self

    def on_damage(self, damage):
        pyglet.clock.unschedule(self.update)

        d = damage / 100
        if self.scalev > 0:
            self.scalev += d * 2
        else:
            self.scalev -= d * 2

        if abs(self.scalev) > 2.2:
            self.delete()

            v = Vec2d(0.5, 0)
            v0 = Vec2d(0, 0)
            for pos in (-v, v0, v):
                spawn_robot(self.body.position + v0)

            level.destroy_one()
        else:
            pyglet.clock.schedule(self.update)

    def update(self, dt):
        x = self.sprite.scale - 1.0
        a = -200 * x
        u = self.scalev
        v = self.scalev = (u + a * dt) * 0.9
        self.sprite.scale += 0.5 * (u + self.scalev) * dt

        if abs(self.scalev) < 1e-2:
            pyglet.clock.unschedule(self.update)

    def delete(self):
        del shape_to_robot[self.shape]
        level.space.remove(self.body, self.shape)
        super().delete()


@big_object
class GasTank(Destroyable):
    SPRITE = 0, 0


@big_object
class Screen1(Destroyable):
    SPRITE = 1, 1


@big_object
class Screen2(Destroyable):
    SPRITE = 2, 0

@big_object
class Computer1(Destroyable):
    SPRITE = 2, 2

@big_object
class Computer2(Destroyable):
    SPRITE = 3, 3

@big_object
class Grille(Destroyable):
    SPRITE = 1, 3

@big_object
class Fans(Destroyable):
    SPRITE = 0, 2

def label(text, font_size, y_ratio):
    return pyglet.text.Label(text,
        font_name='Checkbook',
        font_size=font_size,
        x=window.width//2, y=window.height * y_ratio,
        anchor_x='center', anchor_y='center')


class GameState(Enum):
    INVALID = 0
    NEW_GAME = 1
    LOAD_LEVEL = 2
    PRESHOW = 3
    PLAYING = 4
    PAUSED = 5
    LEVEL_COMPLETE = 6
    GAME_OVER = 7
    GAME_WON = 8
    CONFIRM_EXIT = 9

class Game:
    press_space_to_continue_label = label('press space to continue', 24, 0.25)
    press_space_for_a_new_game_label = label('press space for a new game', 24, 0.25)
    press_space_to_keep_playing_label = label('press space to keep playing', 24, 0.25)

    press_escape_to_exit_label = label('press escape to exit', 24, 0.2)
    press_escape_to_really_exit_label = label('press escape to really exit', 24, 0.2)

    img = pyglet.resource.image('logo.png')
    img.anchor_x = img.width // 2
    img.anchor_y = img.height // 2
    logo = pyglet.sprite.Sprite(img)
    logo.x = window.width // 2
    logo.y = window.height // 2

    labels = {

        GameState.NEW_GAME: [
            label('welcome to', 32, 0.8),
            logo,
            press_space_for_a_new_game_label,
            press_escape_to_exit_label,
        ],

        GameState.LOAD_LEVEL: [
            label('loading...', 64, 0.5),
        ],

        GameState.PRESHOW: [
        ],

        GameState.PLAYING: [],

        GameState.PAUSED: [
            label('[Pause]', 64, 0.5),
            press_space_to_continue_label,
            press_escape_to_exit_label,
        ],

        GameState.LEVEL_COMPLETE: [
            label('Level Complete', 48, 0.5),
            press_space_to_continue_label,
            press_escape_to_exit_label,
        ],

        GameState.GAME_OVER: [
            label('Game Over', 64, 0.5),
            press_space_to_continue_label,
            press_escape_to_exit_label,
        ],

        GameState.GAME_WON: [
            label('You Win', 64, 0.5),
            label('Congratulations!', 48, 0.6),
            press_space_for_a_new_game_label,
            press_escape_to_exit_label,
        ],

        GameState.CONFIRM_EXIT: [
            label('Are You Sure?', 64, 0.5),
            press_space_to_keep_playing_label,
            press_escape_to_really_exit_label,
        ],
    }

    def __init__(self):
        self.lives = 5
        self.level = 0

        self.state = GameState.NEW_GAME
        self.draw_labels = self.labels[self.state]

        self.level_counter = 0
        global level
        level = Level(f"new_game")
        level.start()

    def transition_to(self, state):
        # print(f"transitioning from {self.state} to {state}")

        global level

        # leaving this state
        if (self.state in (GameState.GAME_OVER, GameState.GAME_WON)
            or (self.state == GameState.CONFIRM_EXIT and state == GameState.NEW_GAME)):
            assert state == GameState.NEW_GAME
            self.close()
            global game
            game = Game()
            return
        if state == GameState.CONFIRM_EXIT:
            self.old_state = self.state

        self.state = state

        # transition to new state
        explicit_labels = False
        auto_transition_to = False

        if self.state == GameState.LOAD_LEVEL:
            level.close()
            self.level_counter += 1
            level = Level(f"level{self.level_counter}")
            self.is_final_level = not os.path.isfile(f"maps/level{self.level_counter + 1}.tmx")
            level.start()
            auto_transition_to = GameState.PRESHOW

        if self.state == GameState.PRESHOW:
            try:
                with open(f"maps/level{self.level_counter}.txt", "rt") as f:
                    text = f.read()
            except FileNotFoundError:
                auto_transition_to = GameState.PLAYING
                text = None

            if text:
                font_size = 48
                advance = 0.1
                cursor = 0.9
                explicit_labels = []

                for line in text.split("\n"):
                    explicit_labels.append(label(line, font_size, cursor))
                    cursor -= advance

                    font_size = 18
                    advance = 0.04
                explicit_labels.append(self.press_space_to_continue_label)
                explicit_labels.append(self.press_escape_to_exit_label)

        if explicit_labels:
            self.draw_labels = explicit_labels
        else:
            self.draw_labels = list(self.labels[self.state])
        window.set_exclusive_mouse(self.paused())

        if player:
            player.on_game_state_change()

        if auto_transition_to:
            self.transition_to(auto_transition_to)

    def on_space(self):

        transition_map = {
            GameState.NEW_GAME: GameState.LOAD_LEVEL,
            GameState.LOAD_LEVEL: GameState.PRESHOW,
            GameState.PRESHOW: GameState.PLAYING,
            GameState.PLAYING: GameState.PAUSED,
            GameState.PAUSED: GameState.PLAYING,
            GameState.LEVEL_COMPLETE: GameState.LOAD_LEVEL,
            GameState.GAME_OVER: GameState.NEW_GAME,
            GameState.GAME_WON: GameState.NEW_GAME,
            GameState.CONFIRM_EXIT: GameState.CONFIRM_EXIT,
        }

        if self.state == GameState.CONFIRM_EXIT:
            print(f"cancelling state, going back to {self.old_state}")
            state = self.old_state
        else:
            state = transition_map[self.state]
        self.transition_to(state)

    paused_states = {
        GameState.NEW_GAME,
        GameState.LOAD_LEVEL,
        GameState.PAUSED,
        GameState.GAME_OVER,
        GameState.GAME_WON,
        GameState.CONFIRM_EXIT,
        }

    def paused(self):
        return self.state in self.paused_states

    def close(self):
        window.set_exclusive_mouse(False)

    def on_game_over(self):
        global player
        global reticle

        if player:
            player.close()
            player = None
        if reticle:
            reticle.close()
            reticle = None

    def close(self):
        global level
        self.on_game_over()
        if level:
            level.close()
            level = None

    def on_draw(self):
        for label in self.draw_labels:
            label.draw()


class Level:
    start_position = Vec2d(10, 10)

    def __init__(self, basename):
        self.basename = basename

    def start(self):
        global hud
        global player
        global reticle

        hud = player = reticle = None

        self.load(self.basename)

        self.collision_tiles = self.tiles.layers[0].tiles
        self.upper_left = Vec2d(vector_zero)
        self.lower_right = Vec2d(
            self.tiles.width,
            self.tiles.height
            )

        self.bullet_batch = pyglet.graphics.Batch()
        self.foreground_sprite_group = pyglet.graphics.OrderedGroup(1)

        self.space = pymunk.Space()
        self.draw_options = pymunk.pyglet_util.DrawOptions()
        self.space.gravity = (0.0, 0.0)
        self.construct_collision_geometry()
        self.objects = set()
        self.destroyables = 0

        self.spawn_map_objects()

    def close(self):
        global hud
        global player
        global reticle

        if player:
            player.close()
        if reticle:
            reticle.close()
        if hud:
            hud.close()
        if lighting:
            lighting.clear_lights()

        hud = player = reticle = None

        for o in tuple(self.objects):
            if hasattr(o, "close"):
                o.close()
        self.objects.clear()

    def on_robot_destroyed(self, robot):
        self.objects.discard(robot)
        if not len(robots):
            if game.is_final_level:
                game.transition_to(GameState.GAME_WON)
            else:
                game.transition_to(GameState.LEVEL_COMPLETE)

    def spawn_map_objects(self):
        tilesets = [t for t in self.tiles.tilesets if 'object' in t.name.lower()]
        types = {}
        for tileset in tilesets:
            for tile in tileset.tiles:
                gid = tileset.firstgid + tile.id
                props = {p.name: p.value for p in tile.properties}
                if props.get('cls'):
                    types[gid] = OBJECT_TYPES[props['cls']]

        for obj in self.tiles.layers[1].objects:
            cls = types[obj.gid]

            if issubclass(cls, Destroyable):
                self.destroyables += 1

            opos = Vec2d(obj.x, self.tiles.height * self.tilew - obj.y)
            off = Vec2d(obj.width / 2, obj.height / 2)

            angle = math.radians(obj.rotation)
            center = opos + off.rotated(-angle)

            self.objects.add(
                cls(center, angle=-angle)
            )

    def destroy_one(self):
        self.destroyables -= 1
        if self.destroyables == 0:
            if Boss.instance:
                Boss.instance.start()

    def load(self, basename):
        # we should always save the tmx file
        # then export the json file
        # this function will detect that that's true
        tmx_path = f'maps/{basename}.tmx'
        try:
            tmx_stat = os.stat(tmx_path)
        except FileNotFoundError:
            sys.exit(f"Couldn't find tmx for basename {basename}!")

        lighting.clear()
        self.tiles = tmx.TileMap.load(tmx_path)
        self.maprenderer = MapRenderer(self.tiles)
        lighting.shadow_casters = self.maprenderer.shadow_casters
        for lt in self.maprenderer.light_objects:
            lighting.add_light(lt)
        self.collision_gids = self.maprenderer.collision_gids
        self.tilew = self.maprenderer.tilew
        lighting.tilew = self.tilew  # ugh, sorry

        props = {p.name: p.value for p in self.tiles.properties}
        if 'ambient' in props:
            a = props['ambient']
            lighting.ambient = (a.red / 255, a.green / 255, a.blue / 255)

    def map_to_world(self, x, y=None):
        if y is None:
            y = x[1]
            x = x[0]
        return Vec2d(x * self.tilew, y * self.tilew)

    def world_to_map(self, x, y=None):
        if y is None:
            y = x[1]
            x = x[0]
        return Vec2d(x / self.tilew, y / self.tilew)

    def construct_collision_geometry(self):
        """
        Construct PyMunk collision geometry by studying tileset map.
        """

        # pass 1: RLE encode horizontal runs of tiles into rectangles
        in_rect = False
        startx = None
        x_rects = set()

        def finish_rect():
            nonlocal x
            nonlocal y
            nonlocal startx
            nonlocal in_rect
            in_rect = False
            rect = ((startx, y), (x, y + 1))
            x_rects.add(rect)

        for y in range(0, self.tiles.height):
            y = self.tiles.height - y - 1
            for x in range(0, self.tiles.width):
                tile = self.collision_tile_at(x, y)
                if tile:
                    if not in_rect:
                        in_rect = True
                        startx = x
                elif in_rect:
                    finish_rect()
            if in_rect:
                x += 1
                finish_rect()

        # sort fns for sorting lists of rects
        sort_by_y = lambda box: (box[0][1], box[0][0])
        # we usually sort lowest y coord to the end,
        # this lets us pop efficiently when processing
        # from lowest to highest x
        sort_by_reverse_y = lambda box: (-box[0][1], box[0][0])

        # pass 2: merge rectangles down where possible.
        # (if there are two rectangles adjacent in y
        #  and having identical left and right x edges,
        #  merge them into one big rectangle.)
        xy_rects = []
        sorted_x_rects = list(sorted(x_rects, key=sort_by_reverse_y))
        while sorted_x_rects:
            rect = sorted_x_rects.pop()
            if rect not in x_rects:
                continue
            start, end = rect
            start_x, start_y = start
            end_x, end_y = end
            new_start_y = start_y
            new_end_y = end_y
            while True:
                new_start_y += 1
                new_end_y += 1
                nextrect = ((start_x, new_start_y), (end_x, new_end_y))
                if nextrect not in x_rects:
                    break
                x_rects.remove(nextrect)
                end_y = new_end_y
            xy_rects.append(((start_x, start_y), (end_x, end_y)))

        # pass 3:
        # find all rects who touch each other in y,
        # constructing a dict of r -> set(rects_touching_r)
        # where r is a rect and all the members of the set are also rects.
        #
        # note: we don't have to check if rects are touching on our left or right.
        # if a rect r2 was touching r on the left or the right,
        # then during pass 1 we wouldn't have generated two rects!
        touching = {}
        topdown_rects = list(xy_rects)
        topdown_rects.sort(key=sort_by_reverse_y)
        def r_as_tiles(r):
            return ( (r[0][0]//16, r[0][1]//16), (r[1][0]//16, r[1][1]//16))
        def r_as_tiles_str(r):
            r = r_as_tiles(r)
            return f"(({r[0][0]:2}, {r[0][1]:2}), ({r[1][0]:2}, {r[1][1]:2}))"
        def r_touches(r, r2):
            s = touching.get(r)
            if not s:
                s = set()
                touching[r] = s
            s.add(r2)
            # print(f"{r_as_tiles_str(r)} TOUCHES {r_as_tiles_str(r2)}")
        while topdown_rects:
            r = topdown_rects.pop()
            (x, y), (end_x, end_y) = r
            skip_y = y
            check_y = end_y
            for r2 in reversed(topdown_rects):
                (x2, y2), (end_x2, end_y2) = r2
                if y2 < check_y:
                    # on same y coordinate as us, skip
                    continue
                if y2 != check_y:
                    # too far away in y, all subsequent rects will also be too far away, stop
                    break

                # r2.topleft.y is the same as r.bottomright.y.
                # so if the two rects overlap in x, they're touching.
                # how do we determine that?  easy!
                #
                # there are six possible scenarios:
                #
                # 1. rrrr        no overlap, r < r2
                #         r2r2
                #
                # 2. rrrr           overlap, on the left side of r2
                #      r2r2
                #
                # 3. rrrrrrrr       overlap, r2 is inside r
                #      r2r2
                #
                # 4.   rrrr         overlap, r is inside r2
                #    r2r2r2r2
                #
                # 5.   rrrr         overlap, on the right side of r2
                #    r2r2
                #
                # 6.      rrrr   no overlap, r > r2
                #    r2r2
                #
                # so we just check for 1 and 6.
                # if either is true, we don't overlap.
                # otherwise we do.
                if not ((end_x <= x2) or (end_x2 <= x)):
                    r_touches(r, r2)
                    r_touches(r2, r)

        # pass 4:
        # construct "blobs" of touching rects.
        #
        # pull out a rect and put it in a set.
        # then pull out all rects that touch it and put them in the set too,
        # and all rects that touch *that*, ad infinitum.
        # keep iterating until we don't find any new rects.
        # that's a blob.  repeat until no rects left.
        final_rects = set(xy_rects)
        blobs = []
        while final_rects:
            r = final_rects.pop()
            # print(f"blob, starting with {r_as_tiles_str(r)}")
            blob = set([r])
            check = set([r])
            while check:
                check_next = set()
                for r in check:
                    neighbors = touching.get(r, ())
                    for r2 in neighbors:
                        if r2 not in blob:
                            # print(f"  {r_as_tiles_str(r)} touches {r_as_tiles_str(r2)}")
                            blob.add(r2)
                            final_rects.remove(r2)
                            check_next.add(r2)
                check = check_next
            blobs.append(blob)

        # pass 5:
        # pass 4 produced "blobs", which are sets of boxes
        # that are all touching (you can reach any tile from
        # any other tile in the blob, but you cannot reach any
        # tile in any other other blob).
        #
        # however! just creating those boxes like layer cakes
        # means that there are cracks between them:
        #            ___
        #          _[___] /___  like here for example
        #         [_____] \
        #
        # And if something hits that crack JUST RIGHT you can
        # get unpredictable collisions.
        #
        # So we "spackle" in these cracks with an extra box:
        #            ___
        #          _[___#
        #         [_____#
        # Just a 1x2 box stacked on top of the two existing boxes,
        # straddling the crack.  Since it's static geometry it
        # won't give Chipmunk a tummyache.
        #
        # How do we find cracks?  They appear at the leftmost
        # (and rightmost) tile of the box where there's a tile
        # above us--or below us.
        #
        # Minor optimization:
        # If there are tiles above and below
        #            ___
        #          _[___]
        #         [_____] <--- like here for example
        #           [___]
        # create a 1x3 tile here.  (Actually it needs to be
        # "height of middle box + 2" tall.)
        #
        # Minor lurking bug:
        # This algorithm assumes that there are no other boxes within
        # a tile of our blob.  (If there were, we'd be connected to them.)
        # This means that the algorithm won't generate spackle between a
        # blob and the edge of the level.  This shouldn't be a problem
        # because bullets / players / monsters can never wedge into those
        # cracks.

        def print_blob_in_tiled_coordinates(blob, prefix=""):
            # this lets you check blobs against the coordinates
            # in the map that tiled shows you on its status bar
            a = []
            print(prefix + "{")
            for rect in sorted(blob, key=sort_by_reverse_y):
                (x1, y1), (x2, y2) = rect
                y1 = (self.tiles.height + 0) - (y1 + 0)
                y2 = (self.tiles.height + 0) - (y2 + 0)
                print(f"{prefix}({x1}, {y2}, {x2}, {y1}),")
            s = ", ".join(a)
            print(prefix + "}")


        # spackling is shut off.
        # chipmunk will collide on *both* walls,
        # and that kills bouncy shots.
        # with a higher hz and slower shots we're
        # not having warping problems.
        if 0:
            blob_lists = []
            for blob in blobs:
                spackles = set()
                def add_spackle(x1, y1, x2, y2):
                    new_rect = ((x1, y1), (x2, y2))
                    if new_rect in spackles:
                        return
                    if new_rect in rect:
                        return
                    spackles.add(new_rect)

                for rect in blob:
                    def single_pass(iterator):
                        nonlocal rect
                        spackled_above = spackled_below = False
                        y_above = rect[0][1] - 1
                        y_below = rect[1][1]
                        for x in iterator:
                            tile_above = self.collision_tile_at(x, y_above)
                            tile_below = self.collision_tile_at(x, y_below)
                            if (tile_above and tile_below
                                and not (spackled_above or spackled_below)):
                                # the "1x3" tile
                                add_spackle(x, y_above, x+1, y_below + 1)
                                break
                            if tile_above:
                                # 1x2 tile going up
                                add_spackle(x, y_above, x+1, y_above + 2)
                                if spackled_below:
                                    break
                                spackled_above = True
                            if tile_below:
                                # 1x2 tile going down
                                add_spackle(x, y_below - 1, x + 1, y_below + 1)
                                if spackled_above:
                                    break
                                spackled_below = True

                    # l-r pass
                    single_pass(range(rect[0][0], rect[1][0]))
                    # rl- pass
                    single_pass(range(rect[1][0] - 1, rect[1][0] - 1, -1))

        #     # print("--")
        #     # print("(printing these in tiled coordinates, YOU'RE WELCOME)")
        #     # print("blob")
        #     # print_blob_in_tiled_coordinates(blob)
        #     # print()
        #     # print("spackles")
        #     # print_blob_in_tiled_coordinates(spackles)
        #     # print()
        #     new_blob = list(spackles)
        #     new_blob.extend(blob)
        #     blob_lists.append(new_blob)

        # blobs = blob_lists
        blobs = [sorted(list(blob)) for blob in blobs]


        # print("COLLISION BLOBS")
        # print("Total collision blobs:", len(blobs))
        # print("reminder: blobs include spackle at this point.")
        # # print("Top-left corner of highest rect in each blob:")
        # # blobs.sort(key=lambda blob:(blob[0][0][1], blob[0][0][0]))
        # for i, blob in enumerate(blobs):
        #     print(f"blob #{i}:")
        #     print_blob_in_tiled_coordinates(blob, "  ")

        self.space = pymunk.Space()
        self.draw_options = pymunk.pyglet_util.DrawOptions()
        self.space.gravity = (0, 0)

        # filter only lets through things that cares about
        # e.g. "player collision filter" masks out things the player shouldn't collide with
        self.wall_only_collision_filter = pymunk.ShapeFilter(mask=CollisionType.WALL &  ~CollisionType.PLAYER)

        self.player_collision_filter = pymunk.ShapeFilter(
            group=CollisionType.PLAYER,
            mask=pymunk.ShapeFilter.ALL_MASKS ^ (CollisionType.PLAYER | CollisionType.PLAYER_BULLET))

        self.player_bullet_collision_filter = pymunk.ShapeFilter(
            group=CollisionType.PLAYER_BULLET,
            mask=pymunk.ShapeFilter.ALL_MASKS ^ (CollisionType.PLAYER | CollisionType.PLAYER_BULLET))

        self.robot_collision_filter = pymunk.ShapeFilter(
            group=CollisionType.ROBOT_BULLET,
            mask=pymunk.ShapeFilter.ALL_MASKS ^ (CollisionType.ROBOT | CollisionType.ROBOT_BULLET))

        self.robot_bullet_collision_filter = pymunk.ShapeFilter(
            group=CollisionType.ROBOT_BULLET,
            mask=pymunk.ShapeFilter.ALL_MASKS ^ (CollisionType.ROBOT | CollisionType.ROBOT_BULLET))

        for (type1, type2, fn) in (
            (CollisionType.PLAYER_BULLET, CollisionType.WALL,   on_player_bullet_hit_wall),
            (CollisionType.PLAYER_BULLET, CollisionType.ROBOT,  on_player_bullet_hit_robot),
            (CollisionType.ROBOT_BULLET,  CollisionType.WALL,   on_robot_bullet_hit_wall),
            (CollisionType.ROBOT_BULLET,  CollisionType.PLAYER, on_robot_bullet_hit_player),

            (CollisionType.ROBOT,         CollisionType.WALL,   on_robot_hit_wall),
            ):
            ch = self.space.add_collision_handler(int(type1), int(type2))
            ch.pre_solve = fn

        for blob in blobs:
            (r0x, r0y), (r0end_x, r0end_y) = blob[0]
            body = pymunk.Body(body_type=pymunk.Body.STATIC)
            body.position = Vec2d(r0x, r0y)
            self.space.add(body)
            for r in blob:
                (x, y), (end_x, end_y) = r
                vertices = [
                    (    x - r0x,     y - r0y),
                    (end_x - r0x,     y - r0y),
                    (end_x - r0x, end_y - r0y),
                    (    x - r0x, end_y - r0y),
                    ]
                shape = pymunk.Poly(body, vertices)
                shape.collision_type = CollisionType.WALL
                shape.elasticity = 1.0
                self.space.add(shape)

        # finally, draw a square-donut-shaped collision region
        # around the entire level, to trap the player inside.
        # (the boxes overlap in the four corners but this is harmless for static geometry.)

        # chipmunk coordinate space is *pixel space*
        def add_box_from_bb(rect):
            start, end = rect
            width = end.x - start.x
            height = end.y - start.y
            center_x = start.x + (width >> 1)
            center_y = start.y + (height >> 1)

            body = pymunk.Body(body_type=pymunk.Body.STATIC)
            body.position = Vec2d(center_x, center_y)
            shape = pymunk.Poly.create_box(body, (width, height))
            # print(f"bounding box, center {center_x} {center_y} width {width} height {height}")
            shape.collision_type = CollisionType.WALL
            shape.elasticity = 1.0
            self.space.add(body, shape)

        boundary_delta = Vec2d(100, 100)
        boundary_upper_left = self.upper_left - boundary_delta
        boundary_lower_right = self.lower_right + boundary_delta

        add_box_from_bb((boundary_upper_left, Vec2d(boundary_lower_right.x, self.upper_left.y)))
        add_box_from_bb((boundary_upper_left, Vec2d(self.upper_left.x, boundary_lower_right.y)))
        add_box_from_bb((Vec2d(self.lower_right.x, boundary_upper_left.y), boundary_lower_right))
        add_box_from_bb((Vec2d(boundary_upper_left.x, self.lower_right.y), boundary_lower_right))

    def on_draw(self):
        self.maprenderer.render()

    def position_to_tile_index(self, x, y=None):
        if y is None:
            # x is a Vec2d or maybe a tuple
            # they both behave like a sequence of length 2
            assert len(x) == 2
            y = x[0]
            x = x[1]
        y = self.tiles.height - y - 1
        index = y * self.tiles.width + x
        assert index < len(self.collision_tiles)
        return index

    def tile_index_to_position(self, index):
        y = self.tiles.height - (index // self.tiles.width) - 1
        x = index - (y * self.tiles.width)
#        y *= self.tiles.tileheight
#        x *= self.tiles.tilewidth
        return Vec2d(x, y)

    def collision_tile_at(self, x, y=None):
        # for collision tiles outside the level, just return -1
        if not ((0 <= x < self.tiles.width) and (0 <= y < self.tiles.height)):
            return -1
        gid = self.collision_tiles[self.position_to_tile_index(x, y)].gid
        return gid in self.collision_gids




class BulletColor(IntEnum):
    BULLET_COLOR_INVALID = 0
    BULLET_COLOR_WHITE = 1
    BULLET_COLOR_RED = 2

class BulletShape(IntEnum):
    BULLET_SHAPE_INVALID = 0
    BULLET_SHAPE_NORMAL = 1
    BULLET_SHAPE_TINY = 2


PLAYER_BASE_DAMAGE = 100

shape_to_bullet = {}

BulletClasses = []
def add_to_bullet_classes(cls):
    BulletClasses.append(cls)
    return cls

class BulletBase:
    offset = Vec2d(0.0, 0.0)
    light_radius = 200

    # in subclasses, this is a list of bullets that died during this tick.
    # we don't stick them immediately into the freelist,
    # because they might still be churning around inside pymunk.
    # so we add them to the end of freelist at the end of the tick.
    finishing_tick = None
    # and naturally this is a freelist of (subclass) objects.
    freelist = None

    def __init__(self):
        pass

    @classmethod
    def fire(cls, shooter, vector, modifier):
        if cls.freelist:
            b = cls.freelist.pop()
        else:
            b = cls()
        bullets.add(b)
        if modifier.count == 3:
            rotated_ccw = vector.rotated(math.pi / 12) # 15 degrees
            rotated_cw = vector.rotated(-math.pi / 12) # -15 degrees
            # TODO HACK okay, this is evil
            # we need to spawn three bullets with all the other settings
            # so we create two more bullets but hack modifier.count to be 1
            # temporarily
            modifier.count = 1
            b.fire(shooter, rotated_ccw, modifier)
            b.fire(shooter, rotated_cw, modifier)
            modifier.count = 3
        else:
            assert modifier.count == 1
        b._fire(shooter, vector, modifier)
        return b

    def _fire(self, shooter, velocity, modifier):
        self.shooter = shooter
        self.damage = int(PLAYER_BASE_DAMAGE * modifier.damage_multiplier)
        self.cooldown = int(random.randrange(*shooter.cooldown_range) * modifier.cooldown_multiplier)

        self.spent = False

    def close(self):
        bullets.discard(self)
        self.__class__.finishing_tick.append(self)

    def on_collision_wall(self, shape):
        self.spent = True
        self.draw_impact()
        self.close()

    # we rely on collision filters to prevent
    # the wrong kind of collision from happening

    def on_collision_player(self, shape):
        assert self.shooter != player
        player.on_damage(self.damage)
        self.spent = True
        self.draw_impact()
        self.close()

    def on_collision_robot(self, shape):
        assert self.shooter is player
        robot = shape_to_robot.get(shape)
        if robot:
            robot.on_damage(self.damage)
            self.spent = True
            self.draw_impact()
            self.close()

    def on_draw(self):
        pass

    def draw_impact(self):
        Impact.emit(level.map_to_world(self.position), self.velocity)
        light_flash(self.position, (1.0, 0.9, 0.5), 50)

def anchor_image_to_center(image):
    image.anchor_x = image.anchor_y = image.width // 2
    return image

def load_centered_image(filename):
    image = pyglet.resource.image(filename)
    anchor_image_to_center(image)
    return image


bullet_image = load_centered_image("bullet.png")
tiny_bullet_image = load_centered_image("tiny_bullet.png")
red_bullet_image = load_centered_image("red_bullet.png")
tiny_red_bullet_image = load_centered_image("tiny_red_bullet.png")

@add_to_bullet_classes
class Bullet(BulletBase):
    finishing_tick = []
    freelist = []

    def __init__(self):
        self.bounces = 0
        self.last_bounced_wall = None

        # bullets are circles with diameter 1/2 the same as tile width (and tile height)
        assert level.tiles.tileheight == level.tiles.tilewidth

        images = (bullet_image, red_bullet_image)
        radius = player.radius / 3
        body = pymunk.Body(mass=1, moment=pymunk.inf, body_type=pymunk.Body.DYNAMIC)
        shape = pymunk.Circle(body, radius=radius, offset=self.offset)
        shape_to_bullet[shape] = self

        self.normal_bullet = (body, images, radius, shape)

        images = (tiny_bullet_image, tiny_red_bullet_image)
        radius = player.radius / 6
        body = pymunk.Body(mass=1, moment=pymunk.inf, body_type=pymunk.Body.DYNAMIC)
        shape = pymunk.Circle(body, radius=radius, offset=self.offset)
        shape_to_bullet[shape] = self

        self.small_bullet = (body, images, radius, shape)

        self.red_bullet_color = (1.0, 0.0, 0.0)
        self.normal_bullet_color = (1.0, 1.0, 1.0)

    def _fire_basics(self, shooter, vector, modifier):
        self.bounces = modifier.bounces
        self.last_bounced_wall = None

        vector = Vec2d(vector).normalized()
        self.velocity = Vec2d(vector) * shooter.bullet_speed * modifier.speed

        bullet_offset = Vec2d(vector) * (shooter.radius + self.radius)
        self.position = Vec2d(shooter.position) + bullet_offset

        self.body.position = Vec2d(self.position)
        self.body.velocity = Vec2d(self.velocity)
        level.space.reindex_shapes_for_body(self.body)
        self.shape.collision_type = shooter.bullet_collision_type
        self.shape.filter = shooter.bullet_collision_filter
        self.shape.elasticity = 1.0

        self.body.velocity = self.velocity
        level.space.add(self.body, self.shape)
        self.create_visuals()
        self.on_update(0)

    def _fire(self, shooter, vector, modifier):
        if modifier.shape == BulletShape.BULLET_SHAPE_TINY:
            bullet_shape = self.small_bullet
            self.light_radius = 120
        else:
            bullet_shape = self.normal_bullet
            self.light_radius = 200

        body, images, radius, shape = bullet_shape
        if modifier.color == BulletColor.BULLET_COLOR_RED:
            image = images[1]
            self.light_color = self.red_bullet_color
        else:
            image = images[0]
            self.light_color = self.normal_bullet_color

        self.body = body
        self.image = image
        self.radius = radius
        self.shape = shape

        super()._fire(shooter, vector, modifier)
        self._fire_basics(shooter, vector, modifier)

    def create_visuals(self):
        self.light = Light(self.position, self.light_color, self.light_radius)
        lighting.add_light(self.light)
        self.sprite = pyglet.sprite.Sprite(
            self.image,
            batch=level.bullet_batch,
            group=level.foreground_sprite_group
        )

    def update_visuals(self):
        self.light.position = self.position

        sprite_coord = level.map_to_world(self.position)
        # move
        # sprite_coord -= Vec2d(64, 64)
        self.sprite.position = sprite_coord

    def destroy_visuals(self):
        self.sprite.delete()
        self.sprite = None
        lighting.remove_light(self.light)

    def close(self):
        super().close()
        level.space.remove(self.body, self.shape)
        self.destroy_visuals()

    def on_update(self, dt):
        old = self.position
        self.position = Vec2d(self.body.position)
        self.update_visuals()

    def on_collision_wall(self, wall_shape):
        if (wall_shape != None) and (self.last_bounced_wall == wall_shape):
            # I don't think this ever happens anymore
            return True
        if self.bounces:
            self.bounces -= 1
            self.last_bounced_wall = wall_shape
            # print(f"bouncing, {self.bounces} bounces left")
            return True
        super().on_collision_wall(wall_shape)


@add_to_bullet_classes
class BossKillerBullet(Bullet):
    finishing_tick = []
    freelist = []
    radius = 0.7071067811865476
    light_color = (2, 2, 10.0)
    light_radius = 400
    image = load_centered_image("white_circle.png")

    def __init__(self):
        self.body = pymunk.Body(mass=1, moment=pymunk.inf, body_type=pymunk.Body.DYNAMIC)
        self.shape = pymunk.Circle(self.body, radius=self.radius, offset=(0, 0))
        self.position = (0, 0)
        shape_to_bullet[self.shape] = self

    def _fire(self, shooter, vector, modifier):
        BulletBase._fire(self, shooter, vector, modifier)
        def really_fire():
            self._fire_basics(shooter, vector, modifier)
        self.really_fire = really_fire
        self.t = 0
        self.sparks_t = 0
        self.sparks_repeat_t = 0.1
        self.fire_t = 0.75
        self.fired = False

    def on_update(self, dt):
        if self.fired:
            super().on_update(dt)
            return

        if not player and reticle:
            self.close()
            return


        self.t += dt
        if self.t > self.fire_t:
            self.fired = True
            self.really_fire()
            return

        if self.t > self.sparks_t:
            # sparks
            player_edge = reticle.offset.normalized() * player.radius
            player_screen = level.map_to_world(player.position + player_edge)
            Impact.emit(player_screen, reticle.offset)
            self.sparks_t += self.sparks_repeat_t
            self.sparks_t *= 0.8


@add_to_bullet_classes
class Rocket(Bullet):
    finishing_tick = []
    freelist = []

    SPRITE = (6, 1)

    def create_visuals(self):
        sprite_coord = level.map_to_world(self.position)
        self.rocket = RobotSprite(sprite_coord, self.SPRITE)
        self.smoke = Smoke(sprite_coord)
        self.rocket.angle = self.velocity.get_angle()
        self.light = Light(self.position, (0.6, 0.4, 0), 50)
        lighting.add_light(self.light)

    def update_visuals(self):
        sprite_coord = level.map_to_world(self.position)
        self.rocket.position = sprite_coord
        self.smoke.set_world_position(sprite_coord, self.velocity)
        self.rocket.angle = self.velocity.get_angle()
        self.light.position = self.position - self.velocity * 0.06

    def destroy_visuals(self):
        self.rocket.delete()
        self.rocket = None
        self.smoke.destroy()
        lighting.remove_light(self.light)

    def on_update(self, dt):
        to_player = (player.body.position - self.body.position).normalized()

        speed = self.body.velocity.length
        u = self.body.velocity.normalized()
        v = to_player * u.length
        frac = 0.1 ** dt

        newv = (u * frac + v * (1.0 - frac)).normalized() * speed
        self.velocity = self.body.velocity = newv

        super().on_update(dt)


@add_to_bullet_classes
class RailgunBullet(BulletBase):
    finishing_tick = []
    freelist = []

    colors = [
        None,
        (1.0, 1.0, 1.0, 0.5),
        (1.0, 0.0, 0.0, 0.5),
        ]

    radius = 0

    def __init__(self):
        super().__init__()
        self.rays = []

    def fire_railgun_ray(self, start_point, shooter, vector, modifier, reflected=False):
        vector = Vec2d(vector).normalized()

        long_enough_vector = vector * 150
        railgun_test_endpoint = start_point + long_enough_vector

        collisions = level.space.segment_query(start_point, railgun_test_endpoint,
            self.radius, level.player_bullet_collision_filter)

        # simulate collisions
        for collision in sorted(collisions, key=operator.attrgetter('alpha')):
            if collision.shape.body != shooter.body:
                # Apply impulse
                collision.shape.body.apply_impulse_at_world_point(
                    long_enough_vector * modifier.damage_multiplier,
                    collision.point
                )

            stop = False
            robot = shape_to_robot.get(collision.shape)
            if robot:
                robot.on_damage(self.damage)
                stop = isinstance(robot, Boss)

            if stop or collision.shape.collision_type == CollisionType.WALL:
                hit = start_point + long_enough_vector * collision.alpha
                normal = collision.normal
                break
        else:
            return

        ray_start = level.map_to_world(start_point)
        ray_end = level.map_to_world(hit)
        Impact.emit(ray_end, -vector)

        if not reflected:
            light_flash(start_point, (2.0, 2.0, 2.0), 400)

        self.rays.append(Ray(ray_start, ray_end, width=1, color=self.colors[modifier.color]))
        # print("ADDED RAY", self.rays[-1])

        shot_angle = vector.angle
        if not (math.isnan(normal.x) or math.isnan(normal.y)):
            normal_angle = normal.angle
            normal_plus_90 = normal_angle + (math.pi / 2)
            delta = shot_angle - normal_plus_90
            bounce_angle = shot_angle - (delta * 2)

            # fudge the hit away from the wall slightly
            # we don't want the second railgun shot to spawn
            # inside the wall
            fudge = Vec2d(0.01, 0).rotated(normal_angle)
            hit += fudge
        else:
            # argh.  give 'em *something*.
            # (tbh I think this usually happens when calculating the *second* railshot)
            bounce_angle = shot_angle + random.randrange(-45, 45) * ((2 * math.pi) / 360)
            fudge = 0

        bounce_vector = Vec2d(1, 0).rotated(bounce_angle)

        # print("railgun shot:")
        # print(f"    start point {start_point}")
        # print(f"          fudge {fudge}")
        # print(f"            hit {hit}")
        # print(f"     shot angle {shot_angle}")
        # print(f"   bounce angle {bounce_angle}")
        # print(f"  bounce vector {bounce_vector}")

        return hit, bounce_vector

    def _fire(self, shooter, vector, modifier):
        super()._fire(shooter, vector, modifier)

        # TODO
        # robots can't fire railguns yet
        assert shooter is player

        offset = reticle.offset.normalized() * player.radius
        start_point = shooter.position + offset

        for i in range(modifier.bounces + 1):
            hit, bounce_vector = self.fire_railgun_ray(
                start_point,
                shooter,
                vector,
                modifier,
                reflected=bool(i)
            )
            start_point = hit
            vector = bounce_vector

        light_flash(hit, radius=90)
        self.growth = 1000

        pyglet.clock.schedule_once(self.die, 0.6)

    def on_update(self, dt):
        for ray in self.rays:
            ray.width *= self.growth ** dt
            c = ray.color
            ray.color = (*c[:3], c[3] - 1.2 * dt)

    def die(self, dt):
        self.close()

    def close(self):
        super().close()
        for ray in self.rays:
            ray.delete()
        self.rays.clear()




# keep these sorted (exept name is always first)
class Weapon:
    def __init__(self, name,
            bounces = 0,
            cls=Bullet,
            count = 1,
            color=BulletColor.BULLET_COLOR_WHITE,
            cooldown_multiplier=1,
            damage_multiplier=1,
            shape=BulletShape.BULLET_SHAPE_NORMAL,
            speed=1,
            sound=default_sound
            ):
        self.name = name
        self.bounces = bounces
        self.cls = cls
        self.color = color
        self.cooldown_multiplier = cooldown_multiplier
        self.count = count
        self.damage_multiplier = damage_multiplier
        self.shape = shape
        self.speed = speed
        self.sound = sound

    def __repr__(self):
        s = f'<Weapon "{self.name}"'
        for attr, default, format in (
            ("bounces",0,''),
            ("cls",Bullet,''),
            ("color",BulletColor.BULLET_COLOR_WHITE,''),
            ("cooldown_multiplier",1,'1.3'),
            ("count",1,''),
            ("damage_multiplier", 1,'1.3'),
            ("shape",BulletShape.BULLET_SHAPE_NORMAL,''),
            ("speed",1,'1.3'),
            ):
            value = getattr(self, attr)
            if value != default:
                if format:
                    try:
                        value = f"{value:{format}}"
                    except ValueError:
                        pass
                s += f" {attr}={value}"
        s += ">"
        return s

    def fire(self, shooter, vector):
        player = self.sound.play()
        player.volume = 0.5
        return self.cls.fire(shooter, vector, self)



def on_robot_hit_wall(arbiter, space, data):
    robot_shape = arbiter.shapes[0]
    wall_shape = arbiter.shapes[1]
    robot = shape_to_robot.get(robot_shape)
    if robot:
        robot.on_collision_wall(wall_shape)
    return True



bullets = set()

def bullet_collision(entity, arbiter):
    bullet_shape = arbiter.shapes[0]
    entity_shape = arbiter.shapes[1]
    bullet = shape_to_bullet.get(bullet_shape)
    if not bullet:
        return

    # only handle the first collision for a bullet
    # (we tell pymunk to forget about the bullet,
    # but it still finishes the current timestep)
    if bullet.spent:
        return False

    attr_name = "on_collision_" + entity
    callback = getattr(bullet, attr_name, None)
    if callback:
        returned = callback(entity_shape)
        if returned is not None:
            return returned

    return True

def on_player_bullet_hit_wall(arbiter, space, data):
    return bullet_collision("wall", arbiter)

def on_robot_bullet_hit_wall(arbiter, space, data):
    return bullet_collision("wall", arbiter)

def on_player_bullet_hit_robot(arbiter, space, data):
    return bullet_collision("robot", arbiter)

def on_robot_bullet_hit_player(arbiter, space, data):
    return bullet_collision("player", arbiter)




class Powerup(IntEnum):
        TWO_SHOT = 1
        DAMAGE_BOOST = 2
        BOUNCE = 4
        RAILGUN = 8

# each powerup gives you approximately 1.4x more power
# but you also give something up
bullet_modifiers = [
    Weapon("triple",
        cooldown_multiplier=0.6,
        count=3,
        damage_multiplier=0.4,
        shape=BulletShape.BULLET_SHAPE_TINY,
        speed=1.3,
        sound=laser2_sound,
        ),
    Weapon("boosted",
        color=BulletColor.BULLET_COLOR_RED,
        cooldown_multiplier=3,
        damage_multiplier=1.6,
        speed=0.7,
        ),
    Weapon("bouncy",
        bounces=1,
        cooldown_multiplier=1.5,
        damage_multiplier=0.8,
        ),
    Weapon("railgun",
        cls=RailgunBullet,
        cooldown_multiplier=1.2,
        damage_multiplier=1.2,
        sound=rail_sound
        ),
    ]

weapon_matrix = []

BOSS_KILLER_ID = 15

for i in range(16):
    if i == 0:
        weapon = Weapon("normal")
        player_level = 0
    elif i == BOSS_KILLER_ID:
        weapon = Weapon("boss killer",
            cls=BossKillerBullet,
            cooldown_multiplier=5,
            damage_multiplier=1000,
            speed=0.2,
            sound=bkill_sound
            )
        player_level = 3
    else:
        weapon = Weapon("")
        names = []
        sound = default_sound
        for bit, delta in enumerate(bullet_modifiers):
            if i & (1<<bit):
                names.append(delta.name)

                weapon.bounces += delta.bounces
                if delta.cls != Bullet:
                    weapon.cls = delta.cls
                if delta.color != BulletColor.BULLET_COLOR_WHITE:
                    weapon.color = delta.color
                weapon.cooldown_multiplier *= delta.cooldown_multiplier
                weapon.count += (delta.count - 1)
                weapon.damage_multiplier *= delta.damage_multiplier
                if delta.shape != BulletShape.BULLET_SHAPE_NORMAL:
                    weapon.shape = delta.shape
                weapon.speed *= delta.speed
                if delta.sound is not default_sound:
                    sound = delta.sound

        weapon.sound = sound

        player_level = 0
        if 'triple' in names:
            player_level = 1
        if 'railgun' in names:
            player_level = 2
        names.append("shot")
        weapon.name = " ".join(names)

    weapon.player_level = player_level
    weapon_matrix.append(weapon)


class Player:
    MAX_HP = 400
    INITIAL_LIVES = 3

    def __init__(self):
        self.cooldown_range = (10, 12)
        self.bullet_collision_filter = level.player_bullet_collision_filter
        self.bullet_collision_type = CollisionType.PLAYER_BULLET
        self.bullet_speed = 40
        # determine position based on first nonzero tile
        # found in player starting position layer
        self.position = level.start_position
        self.velocity = Vec2d(vector_zero)

        # acceleration is a vector we add to velocity every frame
        self.acceleration = Vec2d(vector_zero)
        # this vector has the same theta as acceleration
        # but its length is how fast we eventually want to move
        self.desired_velocity = Vec2d(vector_zero)
        # this is the multiple against a unit vector to determine our top speed
        self.top_speed = 15
        # how many 1/120th of a second frames should it take to get to full speed
        self.acceleration_frames = 30

        self.pause_pressed_keys = []
        self.pause_released_keys = []
        self.movement_keys = []
        # coordinate system has (0, 0) at upper left
        self.movement_vectors = {
            key.UP:    vector_unit_y,
            key.DOWN:  vector_unit_y * -1,
            key.LEFT:  vector_unit_x * -1,
            key.RIGHT: vector_unit_x,
            }
        self.movement_opposites = {
            key.UP: key.DOWN,
            key.DOWN: key.UP,
            key.LEFT: key.RIGHT,
            key.RIGHT: key.LEFT
            }

        self.shooting = False
        self.cooldown = 0
        self.weapon_index = 0

        self.health = self.MAX_HP
        self.lives = self.INITIAL_LIVES

        self.sprite = PlayerRobotSprite(level.map_to_world(self.position))

        self.body = pymunk.Body(mass=1, moment=pymunk.inf, body_type=pymunk.Body.DYNAMIC)
        self.body.position = Vec2d(self.position)
        self.body.velocity_func = self.on_update_velocity

        sprite_radius = self.sprite.sprite.width // 2
        self.radius = level.world_to_map(sprite_radius, 0).x
        # player_shape_radius = Vec2d(0.5, 0.5)
        self.shape = pymunk.Circle(self.body, self.radius)
        self.shape.collision_type = CollisionType.PLAYER
        self.shape.filter = level.player_collision_filter

        self.shape.elasticity = 0.1
        level.space.add(self.body, self.shape)
        self.trail = Trail(self, viewport, level)

        self.light = Light(self.position, PLAYER_GLOW)
        lighting.add_light(self.light)

    def close(self):
        lighting.remove_light(self.light)
        self.light = None

        self.sprite.delete()
        self.sprite = None

    def toggle_weapon(self, bit):
        i = 1 << (bit - 1)
        enabled = bool(self.weapon_index & i)
        if enabled:
            index = self.weapon_index & ~i
        else:
            index = self.weapon_index | i

        if BOSS_KILLER_ID in (index, self.weapon_index):
            hud.set_boss_weapon(not enabled)
        hud.set_weapon_enabled(bit - 1, not enabled)

        weapon = weapon_matrix[index]
        # print(f"Weapon: {weapon}\n")
        self.sprite.level = weapon.player_level
        self.weapon_index = index

    def calculate_speed(self):
        if self.velocity != self.desired_velocity:
            self.velocity = vector_clamp(self.velocity + self.acceleration, self.desired_velocity)

    def calculate_acceleration(self):
        new_acceleration = Vec2d(0, 0)
        handled = set()
        for key in self.movement_keys:
            if key in handled:
                continue
            vector = self.movement_vectors.get(key)
            new_acceleration += vector
            handled.add(key)
            handled.add(self.movement_opposites[key])

        desired_velocity = new_acceleration.normalized() * self.top_speed
        desired_velocity.rotate(reticle.theta - math.pi / 2)

        self.desired_velocity = desired_velocity
        self.acceleration = desired_velocity / self.acceleration_frames

    def on_game_state_change(self):
        if game.paused():
            assert not self.pause_pressed_keys
            assert not self.pause_released_keys
            return

        if not (self.pause_pressed_keys or self.pause_released_keys):
            return

        movement_change = False
        for key in self.pause_released_keys:
            if key in self.pause_pressed_keys:
                self.pause_pressed_keys.remove(key)
            elif key in self.movement_keys:
                movement_change = True
                self.movement_keys.remove(key)
        self.pause_released_keys.clear()

        if not (movement_change or self.pause_pressed_keys):
            return

        new_movement_keys = []
        new_movement_keys.extend(self.pause_pressed_keys)
        new_movement_keys.extend(self.movement_keys)
        self.movement_keys = new_movement_keys
        self.pause_pressed_keys.clear()
        self.calculate_acceleration()

    def on_key_press(self, symbol, modifiers):
        vector = self.movement_vectors.get(symbol)
        if not vector:
            return
        if game.paused():
            self.pause_pressed_keys.insert(0, symbol)
            return
        self.movement_keys.insert(0, symbol)
        self.calculate_acceleration()
        return pyglet.event.EVENT_HANDLED

    def on_key_release(self, symbol, modifiers):
        vector = self.movement_vectors.get(symbol)
        if not vector:
            return
        if game.paused():
            if symbol in self.pause_pressed_keys:
                self.pause_pressed_keys.remove(symbol)
            else:
                self.pause_released_keys.insert(0, symbol)
            return
        if symbol in self.movement_keys:
            self.movement_keys.remove(symbol)
            self.calculate_acceleration()
        return pyglet.event.EVENT_HANDLED

    def on_player_moved(self):
        self.position = self.body.position
        sprite_coordinates = level.map_to_world(self.position)
        self.sprite.position = sprite_coordinates
        self.light.position = self.body.position
        reticle.on_player_moved()

    def on_update_velocity(self, body, gravity, damping, dt):
        velocity = Vec2d(self.velocity)
        body.velocity = velocity
        self.body.velocity = velocity

    def on_update(self, dt):
        # TODO
        # actually use dt here
        # instead of assuming it's 1/60 of a second
        # print(f"\n\n<<<{dt}>>>")
        self.calculate_speed()
        if self.cooldown > 0:
            self.cooldown -= 1
        elif self.shooting:
            modifier = weapon_matrix[self.weapon_index]
            bullet = modifier.fire(self, reticle.offset)
            self.cooldown = bullet.cooldown

        self.sprite.angle = reticle.theta

        # raystart = Vec2d(*self.sprite.position)
        # ray = Vec2d(1, 0).rotated(reticle.theta)
        # self.ray.ends = (
        #     raystart + ray * 16,
        #     raystart + ray * 300
        # )

    def on_damage(self, damage):
        self.health -= damage
        hud.set_health(max(self.health / self.MAX_HP, 0))
        if self.health <= 0:
            self.on_died()

    def respawn(self):
        self.alive = True
        self.health = self.MAX_HP
        self.lives -= 1
        hud.set_health(1.0)
        hud.set_lives(self.lives)
        self.body.position = level.start_position
        self.on_player_moved()
        self.sprite.visible = True
        reticle.sprite.visible = True
        level.space.add(self.body, self.shape)

    alive = True

    def on_died(self):
        self.alive = False
        self.shooting = False
        self.sprite.visible = False
        reticle.sprite.visible = False
        level.space.remove(self.body, self.shape)
        if self.lives:
            pyglet.clock.schedule_once(lambda dt: self.respawn(), 1.5)
        else:
            game.transition_to(GameState.GAME_OVER)


class Reticle:
    def __init__(self):
        self.image = load_centered_image("reticle.png")
        self.sprite = pyglet.sprite.Sprite(self.image, batch=level.bullet_batch, group=level.foreground_sprite_group)
        self.position = Vec2d(0, 0)
        # how many pixels movement onscreen map to one revolution
        self.acceleration = 3000
        self.mouse_multiplier = -(math.pi * 2) / self.acceleration
        # in radians
        self.theta = math.pi * 0.5
        # in pymunk coordinates
        self.magnitude = 3
        self.offset = Vec2d(0, self.magnitude)

    def close(self):
        self.sprite.delete()
        self.sprite = None

    def on_mouse_motion(self, x, y, dx, dy):
        if game.paused():
            return
        if not player.alive:
            return
        if dx:
            self.theta += dx * self.mouse_multiplier
            viewport.angle = self.theta - math.pi / 2
            self.offset = Vec2d(self.magnitude, 0)
            self.offset.rotate(self.theta)
            player.sprite.rotation = self.theta
            player.calculate_acceleration()
            self.on_player_moved()

    def on_mouse_drag(self, x, y, dx, dy, buttons, modifiers):
        if game.paused():
            return
        return self.on_mouse_motion(x, y, dx, dy)

    def on_player_moved(self):
        self.position = Vec2d(player.position) + self.offset
        sprite_coordinates = level.map_to_world(self.position)
        self.sprite.set_position(*sprite_coordinates)

        viewport.position = self.sprite.position + self.offset * 40

    def on_draw(self):
        pass
        # self.sprite.draw()


def is_moving(v):
    """Return True if a vector represents an object that is moving."""
    return v.get_length_sqrd() > 1e-3




robots = set()
shape_to_robot = {}

robot_base_weapon = Weapon("robot base weapon",
    damage_multiplier=1,
    cooldown_multiplier=1,
    speed=1,
    color=BulletColor.BULLET_COLOR_WHITE,
    shape=BulletShape.BULLET_SHAPE_NORMAL,
    cls=Bullet)


class RobotBehaviour: # Dan, you're welcome, you don't know how much I want to omit the 'u'
    def __init__(self, robot):
        self.robot = robot
        # automatically add our overloaded callback
        # to the appropriate list in the robot
        # if we add new overloads, just add the string to this enumeration
        for callback_name in (
            "on_collision_wall",
            "on_damage",
            "on_died",
            "on_update",
            "on_update_velocity",
            ):
            class_method = getattr(self.__class__, callback_name)
            base_class_method = getattr(RobotBehaviour, callback_name)
            if class_method != base_class_method:
                callbacks = getattr(robot, callback_name + "_callbacks")
                callbacks.append(getattr(self, callback_name))

    # for all callbacks, the rule is:
    # if you return a True value, no further
    # callbacks are called.

    def on_collision_wall(self, wall_shape):
        pass

    def on_damage(self, damage):
        pass

    def on_died(self):
        pass

    def on_update(self, dt):
        pass

    def on_update_velocity(self, body, gravity, damping, dt):
        pass


class RobotSleeps(RobotBehaviour):
    # designed to be used in combination with other behaviours.
    # add it *before* behaviours you want to put to sleep.
    # for example:
    #    r = Robot()
    #    RobotShootsAtSquirrels(r)
    #    RobotSleeps(r)
    #    RobotMovesToShoreditch(r)
    #
    # here, the robot sleeping prevents it from moving to Shoreditch,
    # but it shoots at squirrels even while it's otherwise asleep.
    #
    # sleep_interval and active_interval should be expressed in fractional
    # seconds.  they can also be callables, in which case they'll be called
    # each time to provide the next interval.
    def __init__(self, robot, active_interval, sleep_interval):
        super().__init__(robot)
        self.robot = robot
        if not callable(active_interval):
            _active_interval = active_interval
            active_interval = lambda: _active_interval
        if not callable(sleep_interval):
            _sleep_interval = sleep_interval
            sleep_interval = lambda: _sleep_interval
        self.active_interval = active_interval
        self.sleep_interval = sleep_interval

        self.t = 0
        self.sleeping = False
        self.next_t = self.active_interval()

    def on_update(self, dt):
        self.t += dt
        if self.t > self.next_t:
            self.sleeping = not self.sleeping
            self.t -= self.next_t
            if self.sleeping:
                self.next_t = self.sleep_interval()
                self.robot.velocity = self.robot.body.velocity = Vec2d(0, 0)
            else:
                self.next_t = self.active_interval()

        if self.sleeping:
            return True

    def on_collision_wall(self, wall_shape):
        if self.sleeping:
            return True

    def on_update_velocity(self, body, gravity, damping, dt):
        if self.sleeping:
            return True


class RobotShootsConstantly(RobotBehaviour):
    cooldown = 0

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.cooldown = random.randint(100, 200)

    def on_update(self, dt):
        if self.cooldown > 0:
            self.cooldown -= 1
            return

        if not player:
            return

        vector_to_player = Vec2d(player.position) - self.robot.position
        bullet = self.robot.weapon.fire(self.robot, vector_to_player)
        self.cooldown = bullet.cooldown


class RobotShootsOnlyWhenPlayerIsVisible(RobotBehaviour):
    cooldown = 0

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.cooldown = random.randint(100, 200)

    def on_update(self, dt):
        if self.cooldown > 0:
            self.cooldown -= 1
            return

        if not player:
            return

        collision = level.space.segment_query_first(self.robot.position,
            player.position,
            player.radius / 3, # TODO this shouldn't be hard-coded
            level.robot_bullet_collision_filter)
        if collision and collision.shape == player.shape:
            vector_to_player = Vec2d(player.position) - self.robot.position
            bullet = self.robot.weapon.fire(self.robot, vector_to_player)
            self.cooldown = bullet.cooldown


class RobotMovesRandomly(RobotBehaviour):
    countdown = 0
    def __init__(self, robot, speed=None):
        super().__init__(robot)
        # how many units per second
        self.speed = speed or (1 + (random.random() * 2.5))

    def pick_new_vector(self):
        # how many 1/120 tics should we move in this direction?
        self.countdown = random.randint(60, 240)
        self.theta = random.random() * (2 * math.pi)
        self.robot.velocity = Vec2d(self.speed, 0)
        self.robot.velocity.rotate(self.theta)

    def on_collision_wall(self, wall_shape):
        self.pick_new_vector()

    def on_update(self, dt):
        if self.countdown > 0:
            self.countdown -= 1
            return
        self.pick_new_vector()

class RobotChangesDirectionWhenItHitsAWall(RobotBehaviour):
    def __init__(self, robot, directions, speed=None):
        super().__init__(robot)
        self.speed = speed or (1 + (random.random() * 2.5))
        self.directions = [(Vec2d(d).normalized() * self.speed) for d in directions]
        self.robot.velocity = self.robot.body.velocity = directions.pop(0)
        self.backing_away_from_wall = None
        self.still_colliding = False
        self.next_direction = None

    # two-stage process.
    #  stage 1: back out of the wall
    #  stage 2: once we're clear of the wall, switch to the next direction.
    #
    # the trick: chipmunk tells us when we're colliding with a wall.
    # it *doesn't* tell us "oh you stopped colliding with that wall".
    # and afaik there's no direct "am I colliding?" test.

    def on_collision_wall(self, wall_shape):
        self.still_colliding = True
        if not self.backing_away_from_wall:
            self.backing_away_from_wall = wall_shape
            self.directions.append(self.robot.velocity)
            self.next_direction = self.directions.pop(0)
            self.robot.velocity = -self.robot.velocity
            return

    def on_update_velocity(self, body, gravity, damping, dt):
        if not self.backing_away_from_wall:
            return
        if not self.still_colliding:
            self.backing_away_from_wall = None
            self.robot.velocity = self.next_direction
            return
        self.still_colliding = False


class RobotMovesBackAndForth(RobotChangesDirectionWhenItHitsAWall):
    def __init__(self, robot, direction, speed=None):
        super().__init__(robot, [direction, direction.rotated(math.pi)], speed)

class RobotMovesInASquare(RobotChangesDirectionWhenItHitsAWall):
    def __init__(self, robot, direction, speed=None):
        super().__init__(robot, [
            direction,
            direction.rotated(math.pi / 2),
            direction.rotated(math.pi),
            direction.rotated(math.pi * 3 / 2),
            ],
            speed)

class RobotMovesStraightTowardsPlayer(RobotBehaviour):
    def __init__(self, robot):
        super().__init__(robot)
        # how many units per second
        self.speed = (1 + (random.random() * 2.5))

    # TODO if you have time: make it try to go around walls?
    # def on_collision_wall(self, wall_shape):
    #     self.pick_new_vector()

    def on_update(self, dt):
        if not player:
            if self.robot.velocity.x or self.robot.velocity.y:
                self.robot.velocity = Vec2d(0, 0)
            return
        vector = player.position - self.robot.position
        vector = vector.normalized() * self.speed
        self.robot.velocity = vector



class Robot:
    weapon = Weapon("robot base weapon",
        damage_multiplier=1,
        cooldown_multiplier=1,
        speed=1,
        color=BulletColor.BULLET_COLOR_WHITE,
        shape=BulletShape.BULLET_SHAPE_NORMAL,
        cls=Bullet
    )
    radius = 0.7071067811865476

    def __init__(self, position, evolution=0):
        # used only to calculate starting position of bullet
        self.bullet_collision_filter = level.robot_bullet_collision_filter
        self.bullet_collision_type = CollisionType.ROBOT_BULLET
        self.bullet_speed = 15

        self.position = Vec2d(position)
        self.velocity = Vec2d(0, 0)

        self.on_collision_wall_callbacks = []
        self.on_damage_callbacks = []
        self.on_died_callbacks = []
        self.on_update_callbacks = []
        self.on_update_velocity_callbacks = []

        self.evolution = evolution
        self.health = 100 * (evolution + 1)
        self.cooldown_range = (180, 240)
        self.cooldown = 0

        self.create_visuals()
        self.create_body()

        robots.add(self)

    def create_visuals(self):
        self.sprite = EnemyRobotSprite(
            level.map_to_world(self.position),
            self.evolution
        )

    def delete_visuals(self):
        if self.sprite:
            self.sprite.delete()
            self.sprite = None

    def create_body(self):
        self.body = pymunk.Body(mass=1, moment=pymunk.inf, body_type=pymunk.Body.DYNAMIC)
        self.body.position = Vec2d(self.position)
        self.body.velocity_func = self.on_update_velocity

        # robots are square!
        self.shape = pymunk.Poly.create_box(self.body, (1, 1))
        self.shape.collision_type = CollisionType.ROBOT
        self.shape.filter = level.robot_collision_filter
        shape_to_robot[self.shape] = self
        level.space.add(self.body, self.shape)

    def delete_body(self):
        level.space.remove(self.body, self.shape)

    def on_update_velocity(self, body, gravity, damping, dt):
        for fn in self.on_update_velocity_callbacks:
            if fn(body, gravity, damping, dt):
                return
        velocity = Vec2d(self.velocity)
        body.velocity = velocity
        self.body.velocity = velocity

    def on_damage(self, damage):
        for fn in self.on_damage_callbacks:
            if fn(damage):
                return

        self.health -= damage
        if self.health <= 0:
            self.on_died()

    def on_update(self, dt):
        self.position = Vec2d(self.body.position)
        sprite_coordinates = level.map_to_world(self.position)
        self.sprite.position = sprite_coordinates
        if is_moving(self.body.velocity):
            self.sprite.angle = self.body.velocity.angle

        for fn in self.on_update_callbacks:
            if fn(dt):
                return

    def delete(self):
        robots.discard(self)
        self.delete_body()
        self.delete_visuals()
        level.on_robot_destroyed(self)

    close = delete

    def on_died(self):
        for fn in self.on_died_callbacks:
            if fn():
                return
        self.create_death_visuals()
        self.delete()

    def create_death_visuals(self):
        light_flash(self.position, (1.0, 0.6, 0.5), 100, 0.2)
        Kaboom(level.map_to_world(self.position))

    def on_collision_wall(self, wall_shape):
        for fn in self.on_collision_wall_callbacks:
            if fn(wall_shape):
                return


class Boss(Robot):
    SPRITE = None
    radius = 1.2
    instance = None

    health = 800

    started = False

    BEHAVIOUR = RobotShootsConstantly

    def __init__(self, position, angle=0):
        self.angle = angle
        super().__init__(position)
        Boss.instance = self

    def create_body(self):
        self.body = pymunk.Body(mass=pymunk.inf, moment=pymunk.inf, body_type=pymunk.Body.STATIC)
        self.body.position = Vec2d(level.world_to_map(self.position))
        self.body.angle = self.angle
        self.shape = pymunk.Poly.create_box(self.body, (2, 2))
        self.shape.collision_type = CollisionType.ROBOT
        level.space.add(self.body, self.shape)
        shape_to_robot[self.shape] = self

    def delete_body(self):
        del shape_to_robot[self.shape]
        level.space.remove(self.body, self.shape)

    def create_visuals(self):
        position = level.world_to_map(self.position)
        self.sprite = BigSprite(self.position, self.SPRITE, angle=self.angle)
        self.sprite.sprite.color = (0,) * 3
        self.light = Light(position, (0.5, 0.0, 0.0), 300)

    def delete_visuals(self):
        self.sprite.delete()
        lighting.remove_light(self.light)

    def start(self):
        self.started = True
        self.sprite.sprite.color = (255,) * 3
        lighting.add_light(self.light)
        self.BEHAVIOUR(self)
        robots.add(self)

    def update(self, dt):
        to_player = (player.body.position - self.body.position)
        self.body.angle = self.sprite.angle = to_player.angle
        self.light.position = self.body.position

    def on_damage(self, damage):
        if not self.started:
            return
        self.health -= damage
        if self.health < 0:
            self.health = 0
        if self.health == 0:
            self.on_died()

    def delete(self):
        super().delete()
        Boss.instance = None


class SpinningRobot(RobotBehaviour):
    cooldown = 0

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.cooldown = random.randint(100, 200)

    def on_update(self, dt):
        body = self.robot.body
        av = body.angular_velocity
        body.angular_velocity = (av + 1.0 * dt) * 0.9 ** dt

        if self.cooldown > 0:
            self.cooldown -= 1
            return

        v = Vec2d(0, 10).rotated(body.angle)

        for angle in (0, math.pi * 2 / 3, math.pi * 4 / 3):
            bullet = self.robot.weapon.fire(self.robot, v.rotated(angle))
        self.cooldown = bullet.cooldown


@big_object
class Boss1(Boss):
    SPRITE = (2, 2)

    weapon = Weapon("Spinning gun",
        damage_multiplier=5,
        cooldown_multiplier=0.1,
        speed=1,
        color=BulletColor.BULLET_COLOR_WHITE,
        shape=BulletShape.BULLET_SHAPE_TINY,
    )

    BEHAVIOUR = SpinningRobot

    def create_body(self):
        self.body = pymunk.Body(mass=1e4, moment=pymunk.inf, body_type=pymunk.Body.DYNAMIC)
        self.body.position = Vec2d(level.world_to_map(self.position))
        self.body.angle = self.angle
        self.shape = pymunk.Circle(self.body, 0.5)
        self.shape.collision_type = CollisionType.ROBOT
        level.space.add(self.body, self.shape)
        shape_to_robot[self.shape] = self

    def update(self, dt):
        self.light.position = self.body.position
        self.sprite.angle = self.body.angle


@big_object
class Boss2(Boss):
    SPRITE = (2, 0)

    weapon = Weapon("Rockets",
        damage_multiplier=5,
        cooldown_multiplier=1,
        speed=1,
        color=BulletColor.BULLET_COLOR_WHITE,
        shape=BulletShape.BULLET_SHAPE_NORMAL,
        cls=Rocket
    )


class Ray:
    tex = pyglet.resource.texture('ray.png')
    batch = pyglet.graphics.Batch()
    group = pyglet.sprite.SpriteGroup(
        tex,
        gl.GL_SRC_ALPHA,
        gl.GL_ONE_MINUS_SRC_ALPHA,
    )

    @classmethod
    def draw(cls):
        cls.batch.draw()

    __slots__ = (
        '_start', '_end', '_width', '_color', 'vl',
    )

    def __init__(self, start, end, width=2.0, color=(1.0, 1.0, 1.0, 0.5)):
        self._start = Vec2d(start)
        self._end = Vec2d(end)
        self._width = width * 0.5
        self._color = color
        self.vl = self.batch.add(
            4, gl.GL_QUADS, self.group,
            ('v2f/dynamic', (0, 0, 1, 0, 1, 1, 0, 1)),
            ('t2f/dynamic', (0, 0, 0, 1, 1, 1, 1, 0)),
            ('c4f/dynamic', self._color_vals()),
        )
        self._recalculate()

    def __repr__(self):
        return f"<Ray {self._start} {self._end} {self._width} {self._color}>"

    def _color_vals(self):
        return [comp for _ in range(4) for comp in self._color]

    @property
    def color(self):
        return self._color

    @color.setter
    def color(self, v):
        assert len(v) == 4
        self._color = v
        vs = self._color_vals()
        self.vl.colors = self._color_vals()

    @property
    def start(self):
        return self._start

    @start.setter
    def start(self, v):
        self._start = Vec2d(v)
        self._recalculate()

    @property
    def end(self):
        return self._end

    @end.setter
    def end(self, v):
        self._end = Vec2d(v)
        self._recalculate()

    @property
    def ends(self):
        return self._start, self._end

    @end.setter
    def ends(self, v):
        start, end = v
        self._start = Vec2d(start)
        self._end = Vec2d(end)
        self._recalculate()

    @property
    def width(self):
        return self._width * 2.0

    @width.setter
    def width(self, v):
        self._width = v * 0.5
        self._recalculate()

    def _recalculate(self):
        """Update the vertices."""
        forward = self._end - self._start
        across = forward.perpendicular_normal() * self._width
        corners = [
            self._start + across,
            self._start - across,
            self._end - across,
            self._end + across,
        ]
        self.vl.vertices = [f for c in corners for f in c]

    def delete(self):
        self.vl.delete()


def light_flash(position, color=(1.0, 1.0, 1.0), radius=200, duration=0.1):
    light = Light(position, color, radius)
    lighting.add_light(light)
    pyglet.clock.schedule_once(
        lambda dt: lighting.remove_light(light),
        duration
    )


def spawn_robot(map_pos):
    robot = Robot(map_pos, evolution=random.randint(0, 3))
    # RobotMovesRandomly(robot)
    # RobotMovesStraightTowardsPlayer(robot)
    # RobotScuttlesBackAndForth(robot, Vec2d(1, 0))
    # RobotMovesRandomly(robot)
    RobotSleeps(robot, 0.5, 0.5)

    if random.randint(0, 2):
        RobotShootsOnlyWhenPlayerIsVisible(robot)
    else:
        RobotShootsConstantly(robot)

    if random.randint(0, 1):
        RobotMovesInASquare(robot, Vec2d(1, 0))
    else:
        RobotMovesStraightTowardsPlayer(robot)




keypress_handlers = {}
def keypress(key):
    def wrapper(fn):
        keypress_handlers[key] = fn
        return fn
    return wrapper

@keypress(key.ESCAPE)
def key_escape(pressed):
    # print("ESC", pressed)
    if not pressed:
        return

    if game.state != GameState.CONFIRM_EXIT:
        game.transition_to(GameState.CONFIRM_EXIT)
        return

    if game.old_state != GameState.NEW_GAME:
        game.transition_to(GameState.NEW_GAME)
        return

    level.close()
    game.close()
    pyglet.app.exit()

@keypress(key.SPACE)
def key_space(pressed):
    if pressed:
        game.on_space()

@keypress(key._1)
def key_1(pressed):
    if pressed:
        player.toggle_weapon(1)

@keypress(key._2)
def key_2(pressed):
    if pressed:
        player.toggle_weapon(2)

@keypress(key._3)
def key_3(pressed):
    if pressed:
        player.toggle_weapon(3)

@keypress(key._4)
def key_4(pressed):
    if pressed:
        player.toggle_weapon(4)



key_remapper = {
    key.W: key.UP,
    key.S: key.DOWN,
    key.A: key.LEFT,
    key.D: key.RIGHT,
    }


@window.event
def on_key_press(symbol, modifiers):
    symbol = key_remapper.get(symbol, symbol)

    # calling player manually instead of stacking event handlers
    # so we can benefit from remapped keys
    if player and player.on_key_press(symbol, modifiers) == EVENT_HANDLED:
        return
    handler = keypress_handlers.get(symbol)
    if handler:
        handler(True)
        return EVENT_HANDLED

@window.event
def on_key_release(symbol, modifiers):
    symbol = key_remapper.get(symbol, symbol)

    # calling player manually instead of stacking event handlers
    # so we can benefit from remapped keys
    if player and player.on_key_release(symbol, modifiers) == EVENT_HANDLED:
        return
    handler = keypress_handlers.get(symbol)
    if handler:
        handler(False)
        return EVENT_HANDLED

@window.event
def on_mouse_motion(x, y, dx, dy):
    if reticle:
        reticle.on_mouse_motion(x, y, dx, dy)

@window.event
def on_mouse_drag(x, y, dx, dy, buttons, modifiers):
    if reticle:
        reticle.on_mouse_drag(x, y, dx, dy, buttons, modifiers)


LEFT_MOUSE_BUTTON = pyglet.window.mouse.LEFT

@window.event
def on_mouse_press(x, y, button, modifiers):
    if button == LEFT_MOUSE_BUTTON and player and player.alive:
        player.shooting = True

@window.event
def on_mouse_release(x, y, button, modifiers):
    if button == LEFT_MOUSE_BUTTON and player:
        player.shooting = False


@window.event
def on_draw():
    gl.glClearColor(0, 0, 0, 1.0)
    window.clear()
    gl.glEnable(gl.GL_BLEND)
    gl.glDisable(gl.GL_DEPTH_TEST)
    with viewport:
        gl.glClearColor(0xae / 0xff, 0x51 / 0xff, 0x39 / 0xff, 1.0)
        with lighting.illuminate():
            level.on_draw()
            diffuse_system.draw()
            RobotSprite.draw_diffuse()
        level.bullet_batch.draw()
        RobotSprite.draw_emit()

        gl.glBlendFunc(gl.GL_SRC_ALPHA, gl.GL_ONE)
        default_system.draw()
        Ray.draw()
        gl.glBlendFunc(gl.GL_SRC_ALPHA, gl.GL_ONE_MINUS_SRC_ALPHA)
    if hud:
        hud.draw()
    game.on_draw()


def on_update(dt):
    if game.paused():
        return

    level.space.step(dt)
    # print()
    # print("PLAYER", player.body.position)
    if player:
        player.on_player_moved()
        player.on_update(dt)
    for robot in tuple(robots):
        robot.on_update(dt)
    for bullet in tuple(bullets):
        bullet.on_update(dt)
    # print()
    for cls in BulletClasses:
        if cls.finishing_tick:
            cls.freelist.extend(cls.finishing_tick)
            cls.finishing_tick.clear()



pyglet.clock.schedule_interval(on_update, 1/ENGINE_TICKS_IN_HERTZ)
pyglet.clock.schedule_interval(diffuse_system.update, (1.0/30.0))
pyglet.clock.schedule_interval(default_system.update, (1.0/30.0))
pyglet.clock.set_fps_limit(30)

RobotSprite.load()
BigSprite.load()
WideSprite.load()

if Boss.instance:
    Boss.instance.start()

game = Game()

pyglet.app.run()
