from enum import IntEnum
import io
import math
import os
import pprint
import sys
from math import floor

# built from source, removed "inline" from Group_kill_p in */group.h
import lepton

# pip3.6 install pyglet
import pyglet.resource
import pyglet.window.key
from pyglet import gl

# pip3.6 install pymunk
# GAAH
tmp = sys.stdout
sys.stdout = io.StringIO()
import pymunk
sys.stdout = tmp
del tmp
import pymunk.pyglet_util

# Vec2D: 2D vector, mutable
# a = b
# a += (5, 2)
# assert a == b # True
from pymunk import Vec2d
vector_zero = Vec2d.zero()
vector_unit_x = Vec2d(1, 0)
vector_unit_y = Vec2d(0, 1)


# pip3.6 install tmx
import tmx

# pip3.6 install wasabi.geom
# from wasabi.geom.vector import Vector, v
# from wasabi.geom.vector import zero as vector_zero
# from wasabi.geom.vector import unit_x as vector_unit_x
# from wasabi.geom.vector import unit_y as vector_unit_y

from maprenderer import MapRenderer, Viewport, LightRenderer, Light


key = pyglet.window.key
EVENT_HANDLED = pyglet.event.EVENT_HANDLED

window = pyglet.window.Window()
window.set_exclusive_mouse(True)

pyglet.resource.path = [".", "gfx", "gfx/kenney_roguelike/Spritesheet"]
pyglet.resource.reindex()


viewport = Viewport(*window.get_size())
debug_viewport = Viewport(50, 50)


PLAYER_GLOW = (0, 0.4, 0.5)
PLAYER_FIRING = (1.0, 0.95, 0.7)
player_light = Light((10, 10), PLAYER_GLOW)

lighting = LightRenderer(viewport)
lighting.add_light(player_light)


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
    MONSTER = 8
    MONSTER_BULLET = 16



class Robot:
    """Base class for a robot.

    There is some Pyglet magic here that is intended to allow the same
    sprites to be re-rendered with different textures in different phases
    of the draw pipeline. This allows robots to have lights that are not
    shadowed.

    """

    ROWS = COLS = 8

    SPRITE_NUM = 0

    @classmethod
    def load(cls):
        cls.batch = pyglet.graphics.Batch()
        cls.diffuse_tex = pyglet.resource.texture('robots_diffuse.png')
        cls.emit_tex = pyglet.resource.texture('robots_emit.png')

        cls.flip_tex = pyglet.image.Texture(
            cls.diffuse_tex.width,
            cls.diffuse_tex.height,
            gl.GL_TEXTURE_2D,
            cls.diffuse_tex.id
        )
        cls.grid = pyglet.image.ImageGrid(
            image=cls.flip_tex,
            rows=cls.ROWS,
            columns=cls.COLS,
        )
        cls.sprites = {}
        for i, img in enumerate(cls.grid.get_texture_sequence()):
            y, x = divmod(i, cls.COLS)
            y = cls.ROWS - y - 1
            img.anchor_x = img.anchor_y = img.width // 2
            cls.sprites[x, y] = img

    @classmethod
    def draw_diffuse(cls):
        group = next(iter(cls.batch.top_groups), None)
        if group:
            group.texture = cls.diffuse_tex
            cls.batch.draw()

    @classmethod
    def draw_emit(cls):
        group = next(iter(cls.batch.top_groups), None)
        if group:
            group.texture = cls.emit_tex
            cls.batch.draw()

    def __init__(self, pos):
        self.sprite = pyglet.sprite.Sprite(
            self.sprites[self.SPRITE_POS],
            batch=self.batch
        )
        self.pos = pos

    @property
    def pos(self):
        return self.sprite.position

    @pos.setter
    def pos(self, v):
        x, y = v
        self.sprite.position = floor(x + 0.5), floor(y + 0.5)



class PlayerRobot(Robot):
    """Player robot."""

    SPRITE_POS = 0, 0

    def __init__(self, pos, level=0):
        super().__init__(pos)
        self.level = level

    @property
    def level(self):
        return self._level

    @level.setter
    def level(self, v):
        if not (0 <= v < 4):
            raise ValueError(
                f'{type(self).__name__}.level must be 0-3 (not {v})'
            )
        self._level = v
        self.sprite.image = self.sprites[0, self._level]


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


class Level:
    def __init__(self, basename):
        self.load(basename)

        self.collision_tiles, self.player_position_tiles = (layer.tiles for layer in self.tiles.layers)
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

    def load(self, basename):
        # we should always save the tmx file
        # then export the json file
        # this function will detect that that's true
        tmx_path = basename + ".tmx"
        try:
            tmx_stat = os.stat(tmx_path)
        except FileNotFoundError:
            sys.exit(f"Couldn't find tmx for basename {basename}!")

        self.tiles = tmx.TileMap.load(tmx_path)
        self.maprenderer = MapRenderer(self.tiles)
        lighting.shadow_casters = self.maprenderer.shadow_casters
        self.collision_gids = self.maprenderer.collision_gids
        self.tilew = self.maprenderer.tilew
        lighting.tilew = self.tilew  # ugh, sorry

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
            blob = list(blob)
            blob.sort(key=sort_by_y)
            blobs.append(blob)

        # print("COLLISION BLOBS")
        # pprint.pprint(blobs)
        # print("Total collision blobs:", len(blobs))
        # print("Top-left corner of highest rect in each blob:")
        # blobs.sort(key=lambda blob:(blob[0][0][1], blob[0][0][0]))
        # for blob in blobs:
        #     (x, y), (end_x, end_y) = r_as_tiles(blob[0])
        #     print(f"    ({x:3}, {y:3})")

        self.space = pymunk.Space()
        self.draw_options = pymunk.pyglet_util.DrawOptions()
        self.space.gravity = (0, 0)
        self.player_collision_filter = pymunk.ShapeFilter(group=CollisionType.PLAYER | CollisionType.PLAYER_BULLET)
        ch = self.space.add_collision_handler(int(CollisionType.PLAYER_BULLET), int(CollisionType.WALL))
        ch.pre_solve = on_bullet_hit_wall
        # ch = self.space.add_collision_handler(int(CollisionType.PLAYER), int(CollisionType.WALL))
        # ch.pre_solve = on_player_hit_wall

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
                shape.elasticity = 0.0
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
            shape.elasticity = 0.0
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
        gid = self.collision_tiles[self.position_to_tile_index(x, y)].gid
        return gid in self.collision_gids


bullet_freelist = []
bullets_finishing_tick = []
shape_to_bullet = {}

bullet_flare = pyglet.image.load("flare3.png")

class Bullet:
    offset = Vec2d(0.0, 0.0)
    def __init__(self):
        # print()
        # print("--")
        # print("-- bullet __init__")
        self.image = bullet_flare

        # self.body = pymunk.Body(mass=1, moment=pymunk.inf, body_type=pymunk.Body.DYNAMIC)
        self.body = pymunk.Body(mass=1, moment=pymunk.inf, body_type=pymunk.Body.DYNAMIC)
        self.speed = Vec2d(1, 0) * 40
        self.body.velocity_func = self.on_update_velocity
        # print("BULLET BODY", hex(id(self.body)), self.body)

        # makebullet a circle with diameter 1/2 the same as tile width (and tile height)
        assert level.tiles.tileheight == level.tiles.tilewidth
        self.radius = player.radius / 3
        self.shape = pymunk.Circle(self.body, radius=self.radius, offset=self.offset)
        self.shape.collision_type = CollisionType.PLAYER_BULLET
        self.shape.filter = level.player_collision_filter
        shape_to_bullet[self.shape] = self

        self.initialize()

    def initialize(self):
        self.collided = False
        bullet_offset = Vec2d(player.radius + self.radius, 0)
        self.position = Vec2d(player.position) + bullet_offset
        self.body.position = self.position

        self.light = Light(self.position)
        lighting.add_light(self.light)
        # print(f"--initialize bullet! {self} initial position {self.position}")
        self.sprite = pyglet.sprite.Sprite(self.image, batch=level.bullet_batch, group=level.foreground_sprite_group)
        self.on_update(0)
        level.space.reindex_shapes_for_body(self.body)
        level.space.add(self.body, self.shape)

    def on_update(self, dt):
        old = self.position
        self.position = Vec2d(self.body.position)
        # print(f"--bullet update, from {old} to {self.position}")
        sprite_coord = level.map_to_world(self.position)
        # TODO no idea why this seems necessary
        sprite_coord -= Vec2d(64, 64)
        self.sprite.set_position(*sprite_coord)
        self.light.pos = self.position

    def on_update_velocity(self, body, gravity, damping, dt):
        # print("BULLET BODY", hex(id(self.body)), self.body)
        # print("PASSED IN BODY", hex(id(body)), body)
        # print(f"--update bullet velocity {self}")
        self.body.velocity = self.speed
        pass

    def close(self):
        # print(f"--closing bullet {self}")
        bullets.discard(self)
        level.space.remove(self.body, self.shape)
        self.sprite.delete()
        self.sprite = None
        lighting.remove_light(self.light)
        bullets_finishing_tick.append(self)

def new_bullet():
    # return Bullet()
    if bullet_freelist:
        b = bullet_freelist.pop()
        b.initialize()
    else:
        b = Bullet()
    bullets.add(b)
    return b


def transform_pymunk_to_screen(position):
    return Vec2d(
        position.x,
        window.height - position.y
        )


bullets = set()

def on_bullet_hit_wall(arbiter, space, data):
    bullet_shape = arbiter.shapes[0]
    wall_shape = arbiter.shapes[1]
    bullet = shape_to_bullet.get(bullet_shape)

    # only handle the first collision for a bullet
    # (we tell pymunk to forget about the bullet,
    # but it still finishes the current timestep)
    if bullet.collided:
        return False
    bullet.collided = True

    # print("--collision--")
    # print(f"  player position {player.position}")
    # print(f"  bullet {bullet}")
    # print(f"  hit wall shape {wall_shape.bb}")
    # print(f"  at {bullet.body.position}")
    # print(f"  bullet has radius {bullet.radius}")
    if bullet and bullet in bullets:
        bullet.close()
    return False

# def on_player_hit_wall(arbiter, space, data):
#     print("PLAYER HIT WALL", player.body.position)
#     return True

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
            self.position = Vec2d(vector_zero)
        # adjust player position
        # TODO why is this what we wanted?!
        self.position = self.position + Vec2d(0, level.tiles.tileheight)

        # acceleration we add to speed every frame
        self.acceleration = Vec2d(vector_zero)
        # this is literally the self.acceleration as a unit vector
        self.desired_speed = Vec2d(vector_zero)
        # actual current speed
        self.speed = Vec2d(vector_zero)
        self.speed_multiplier = 150
        self.speed = Vec2d(vector_zero)
        self.acceleration_frames = 30 # 30/120 of a second to get to full speed
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
        self.shoot_cooldown = 10
        self.shoot_waiting = 1

        self.sprite = PlayerRobot(level.map_to_world(*self.position))

        self.body = pymunk.Body(mass=1, moment=pymunk.inf, body_type=pymunk.Body.DYNAMIC)
        self.body.position = Vec2d(self.position)
        self.body.velocity_func = self.on_update_velocity

        sprite_radius = self.sprite.sprite.width // 2
        self.radius = level.world_to_map(sprite_radius, 0).x
        # player_shape_radius = Vec2d(0.5, 0.5)
        self.shape = pymunk.Circle(self.body, self.radius)
        self.shape.collision_type = CollisionType.PLAYER
        self.shape.filter = level.player_collision_filter
        self.shape.elasticity = 0.0
        level.space.add(self.body, self.shape)

    def calculate_speed(self):
        if self.speed != self.desired_speed:
            self.speed = vector_clamp(self.speed + self.acceleration, self.desired_speed)

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

        desired_speed = new_acceleration.normalized() * self.speed_multiplier

        self.desired_speed = desired_speed
        self.acceleration = desired_speed / self.acceleration_frames

        # self.body.apply_force_at_local_point(self.desired_speed, Vec2d(0, 0))

    def on_pause_change(self):
        if game.paused:
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
        if game.paused:
            self.pause_pressed_keys.insert(0, symbol)
            return
        self.movement_keys.insert(0, symbol)
        self.calculate_acceleration()
        return pyglet.event.EVENT_HANDLED

    def on_key_release(self, symbol, modifiers):
        vector = self.movement_vectors.get(symbol)
        if not vector:
            return
        if game.paused:
            if symbol in self.pause_pressed_keys:
                self.pause_pressed_keys.remove(symbol)
            else:
                self.pause_released_keys.insert(0, symbol)
            return
        if symbol in self.movement_keys:
            self.movement_keys.remove(symbol)
            self.calculate_acceleration()
        return pyglet.event.EVENT_HANDLED

    def on_player_move(self):
        self.position = self.body.position
        sprite_coordinates = level.map_to_world(self.position)
        self.sprite.pos = sprite_coordinates
        viewport.pos = self.sprite.pos
        player_light.pos = self.body.position

    def on_update_velocity(self, body, gravity, damping, dt):
        velocity = Vec2d(self.speed) * 0.1
        body.velocity = velocity
        self.body.velocity = velocity

    def on_update(self, dt):
        # TODO
        # actually use dt here
        # instead of assuming it's 1/60 of a second
        self.calculate_speed()
        self.shoot_waiting -= 1
        if self.shoot_waiting <= 0:
            self.shoot_waiting = self.shoot_cooldown
            b = new_bullet()

    def on_draw(self):
        self.sprite.draw()


class Reticle:
    def __init__(self):
        self.image = pyglet.image.load("gfx/reticle.png")
        self.sprite = pyglet.sprite.Sprite(self.image, batch=level.bullet_batch, group=level.foreground_sprite_group)
        self.position = Vec2d(0, 0)
        self.acceleration = 0
        # in radians
        self.theta = 0
        # in pymunk coordinates
        self.magnitude = 3

        self.mouse_position = None

    def on_mouse_moved(self, x, y):
        if self.mouse_position == None:
            self.mouse_position = x
        delta = x - self.mouse_position
        self.theta += delta * self.acceleration

    def on_player_moved(self):
        self.position = Vec2d(player.position) + 0



game = Game()
# level = Level("prototype")
level = Level("level1")

Robot.load()

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
        window.set_exclusive_mouse(not game.paused)
        player.on_pause_change()

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
def on_mouse_press(x, y, button, modifiers):
    player.shooting = True

@window.event
def on_mouse_release(x, y, button, modifiers):
    player.shooting = False


@window.event
def on_draw():
    window.clear()
    with viewport:
        with lighting.illuminate():
            level.on_draw()
            Robot.draw_diffuse()
        Robot.draw_emit()
        level.bullet_batch.draw()
        default_system.draw()
    game.on_draw()
    # with debug_viewport:
    #     glScalef(8.0, 8.0, 8.0)
    #     level.space.debug_draw(level.draw_options)


def on_update(dt):
    if game.paused:
        return

    player.on_update(dt)
    level.space.step(dt)
    # print()
    # print("PLAYER", player.body.position)
    player.on_player_move()
    for bullet in bullets:
        # print("BULLET", id(bullet), bullet.body.position)
        bullet.on_update(dt)
    # print()
    if bullets_finishing_tick:
        bullet_freelist.extend(bullets_finishing_tick)
        bullets_finishing_tick.clear()

pyglet.clock.schedule_interval(on_update, 1/120.0)

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

    viewport.w = width
    viewport.h = height
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
    x, y = player.position
    Kaboom((x, y))
    pyglet.clock.schedule_once(fire, expovariate(1.0 / (MEAN_FIRE_INTERVAL - 1)) + 1)


fire()
pyglet.clock.schedule_interval(default_system.update, (1.0/30.0))
pyglet.clock.set_fps_limit(None)


pyglet.app.run()
