#!/usr/bin/env python3

# system includes
from enum import IntEnum
import io
import math
from math import floor, atan2, degrees
import os
import pprint
import random
import sys

# built from source, removed "inline" from Group_kill_p in */group.h
from lepton import default_system

# pip3.6 install pyglet
import pyglet.resource
import pyglet.window.key
from pyglet import gl

pyglet.resource.path = [".", "gfx", "gfx/kenney_roguelike/Spritesheet"]
pyglet.resource.reindex()

# pip3.6 install pymunk
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
import tmx

#

from particles import Trail, Kaboom
from maprenderer import MapRenderer, Viewport, LightRenderer, Light


key = pyglet.window.key
EVENT_HANDLED = pyglet.event.EVENT_HANDLED

window = pyglet.window.Window()
window.set_exclusive_mouse(True)
window.set_caption("My Sincerest Apologies")
window.set_icon(pyglet.image.load('gfx/icon32.png'), pyglet.image.load('gfx/icon16.png'))



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

    def __init__(self, position, sprite_position):
        self.sprite = pyglet.sprite.Sprite(
            self.sprites[tuple(sprite_position)],
            batch=self.batch
        )
        self.position = position

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
        self.sprite.image = self.sprites[self._level, self.ROW]


class EnemyRobotSprite(PlayerRobotSprite):
    """Sprites for the enemies."""
    ROW = 2



class Game:
    def __init__(self):
        self.score = 0
        self.lives = 5

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
        for lt in self.maprenderer.light_objects:
            lighting.add_light(lt)
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

        # filter only lets through things that cares about
        # e.g. "player collision filter" masks out things the player shouldn't collide with
        self.wall_only_collision_filter = pymunk.ShapeFilter(mask=CollisionType.WALL)

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


player_bullet_freelist = []
robot_bullet_freelist = []

# these are lists of bullets that died during this tick.
# we don't stick them immediately into the freelist,
# because they might still be churning around inside pymunk.
# so we add them to the end of freelist at the end of the tick.
player_finishing_tick = []
robot_finishing_tick = []

shape_to_bullet = {}

bullet_flare = pyglet.resource.image("flare3.png")


class BulletColor(IntEnum):
    BULLET_COLOR_INVALID = 0
    BULLET_COLOR_WHITE = 1
    BULLET_COLOR_RED = 2

class BulletShape(IntEnum):
    BULLET_SHAPE_INVALID = 0
    BULLET_SHAPE_NORMAL = 1
    BULLET_SHAPE_TINY = 2


PLAYER_BASE_DAMAGE = 100



BulletClasses = []
def add_to_bullet_classes(cls):
    BulletClasses.append(cls)
    return cls

class BulletBase:
    offset = Vec2d(0.0, 0.0)

    finishing_tick = None
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
        b._fire(shooter, vector, modifier)
        return b

    def _fire(self, shooter, velocity, modifier):
        self.shooter = shooter
        self.damage = int(PLAYER_BASE_DAMAGE * modifier.damage_multiplier)
        self.cooldown = int(random.randrange(*shooter.cooldown_range) * modifier.cooldown_multiplier)

        self.collided = False

    def close(self):
        bullets.discard(self)
        self.__class__.finishing_tick.append(self)

    def on_collision_wall(self, shape):
        pass

    # we rely on collision filters to prevent
    # the wrong kind of collision from happening

    def on_collision_player(self, shape):
        assert self.shooter != player
        player.on_damage(self.damage)

    def on_collision_robot(self, shape):
        assert self.shooter is player
        robot = shape_to_robot.get(shape)
        if robot:
            robot.on_damage(self.damage)

    def on_draw(self):
        pass


@add_to_bullet_classes
class Bullet(BulletBase):
    finishing_tick = []
    freelist = []

    def __init__(self):
        self.body = pymunk.Body(mass=1, moment=pymunk.inf, body_type=pymunk.Body.DYNAMIC)
        self.body.velocity_func = self.on_update_velocity
        self.image = bullet_flare

        # bullets are circles with diameter 1/2 the same as tile width (and tile height)
        assert level.tiles.tileheight == level.tiles.tilewidth
        self.radius = player.radius / 3
        self.shape = pymunk.Circle(self.body, radius=self.radius, offset=self.offset)
        shape_to_bullet[self.shape] = self


    def _fire(self, shooter, vector, modifier):
        super()._fire(shooter, vector, modifier)

        # HANDLE SHAPE
        # HANDLE COLOR

        vector = Vec2d(vector).normalized()
        self.velocity = Vec2d(vector) * shooter.bullet_speed * modifier.speed

        bullet_offset = Vec2d(vector) * (shooter.radius + self.radius)
        self.position = Vec2d(shooter.position) + bullet_offset

        self.body.position = Vec2d(self.position)
        level.space.reindex_shapes_for_body(self.body)
        self.shape.collision_type = shooter.bullet_collision_type
        self.shape.filter = shooter.bullet_collision_filter

        self.light = Light(self.position)
        lighting.add_light(self.light)

        self.sprite = pyglet.sprite.Sprite(self.image, batch=level.bullet_batch, group=level.foreground_sprite_group)
        self.on_update(0)
        self.body.velocity = self.velocity
        level.space.add(self.body, self.shape)

    def close(self):
        super().close()
        level.space.remove(self.body, self.shape)
        self.sprite.delete()
        self.sprite = None
        lighting.remove_light(self.light)

    def on_update(self, dt):
        old = self.position
        self.position = Vec2d(self.body.position)
        self.light.position = self.position

        sprite_coord = level.map_to_world(self.position)
        # TODO no idea why this seems necessary
        sprite_coord -= Vec2d(64, 64)
        self.sprite.position = sprite_coord

    def on_update_velocity(self, body, gravity, damping, dt):
        self.body.velocity = self.velocity


@add_to_bullet_classes
class BossKillerBullet(Bullet):
    finishing_tick = []
    freelist = []


@add_to_bullet_classes
class RailgunBullet(BulletBase):
    finishing_tick = []
    freelist = []

    colors = [
        None,
        (1.0, 1.0, 1.0, 0.5),
        (1.0, 0.0, 0.0, 0.5),
        ]

    radius = 0.1

    def _fire(self, shooter, vector, modifier):
        super()._fire(shooter, vector, modifier)

        # print("railgun FIRE! pew!")
        vector = Vec2d(vector).normalized()

        long_enough_vector = vector * 150
        railgun_test_endpoint = shooter.position + long_enough_vector

        wall_hit = level.space.segment_query_first(shooter.position, railgun_test_endpoint,
            self.radius, level.wall_only_collision_filter)

        collisions = level.space.segment_query(shooter.position, wall_hit.point,
            self.radius, level.player_bullet_collision_filter)

        # simulate collisions
        for collision in collisions:
            if collision.shape == wall_hit.shape:
                continue
            # TODO
            # robots can't fire railguns yet
            assert shooter is player
            robot = shape_to_robot.get(collision.shape)
            if robot:
                robot.on_damage(self.damage)

        offset = reticle.offset.normalized() * player.radius
        ray_start = level.map_to_world(shooter.position + offset)
        ray_end = level.map_to_world(wall_hit.point)

        # print("RAILGUN COLOR", modifier.color)
        self.ray = Ray(ray_start, ray_end, width=3, color=self.colors[modifier.color])
        self.display_countdown = 0.05 # seconds to leave the ray onscreen


    def on_update(self, dt):
        if self.display_countdown >= 0:
            self.display_countdown -= dt
            if self.display_countdown < 0:
                self.close()

    def close(self):
        super().close()
        self.ray.delete()
        self.ray = None




class Weapon:
    def __init__(self, name,
            damage_multiplier=1,
            cooldown_multiplier=1,
            speed=1,
            color=BulletColor.BULLET_COLOR_WHITE,
            shape=BulletShape.BULLET_SHAPE_NORMAL,
            cls=Bullet):
        self.name = name
        self.damage_multiplier = damage_multiplier
        self.cooldown_multiplier = cooldown_multiplier
        self.speed = speed
        self.color = color
        self.shape = shape
        self.cls = cls

    def __repr__(self):
        s = f'<Weapon "{self.name}"'
        for attr, default in (
            ("damage_multiplier", 1),
            ("cooldown_multiplier",1),
            ("speed",1),
            ("color",BulletColor.BULLET_COLOR_WHITE),
            ("shape",BulletShape.BULLET_SHAPE_NORMAL),
            ("cls",Bullet),
            ):
            value = getattr(self, attr)
            if value != default:
                s += f" {attr}={value}"
        s += ">"
        return s

    def fire(self, shooter, vector):
        return self.cls.fire(shooter, vector, self)

"""
    def initialize(self, robot, damage=DEFAULT_DAMAGE):
        self.robot = robot
        vector_to_player = Vec2d(player.position) - robot.position
        vector_to_player = vector_to_player.normalized()

        self.velocity = vector_to_player * self.speed

        bullet_offset = vector_to_player * (robot.radius + self.radius)
        self.position = Vec2d(robot.position) + bullet_offset

        super().initialize(damage)

    def close(self):
        super().close()
        robot_finishing_tick.append(self)


def new_player_bullet():
    if player_bullet_freelist:
        b = player_bullet_freelist.pop()
        b.initialize()
    else:
        b = PlayerBullet()
    bullets.add(b)
    return b

def new_robot_bullet(robot):
    if robot_bullet_freelist:
        b = robot_bullet_freelist.pop()
        b.initialize(robot)
    else:
        b = RobotBullet(robot)
    bullets.add(b)
    return b
"""


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

    # only handle the first collision for a bullet
    # (we tell pymunk to forget about the bullet,
    # but it still finishes the current timestep)
    if bullet.collided:
        return False
    bullet.collided = True

    attr_name = "on_collision_" + entity
    callback = getattr(bullet, attr_name, None)
    if callback:
        callback(entity_shape)

    if bullet and bullet in bullets:
        bullet.close()
    return False

def on_player_bullet_hit_wall(arbiter, space, data):
    return bullet_collision("wall", arbiter)

def on_robot_bullet_hit_wall(arbiter, space, data):
    return bullet_collision("wall", arbiter)

def on_player_bullet_hit_robot(arbiter, space, data):
    return bullet_collision("robot", arbiter)

def on_robot_bullet_hit_player(arbiter, space, data):
    return bullet_collision("player", arbiter)


# def on_player_hit_wall(arbiter, space, data):
#     print("PLAYER HIT WALL", player.body.position)
#     return True



class Powerup(IntEnum):
        TWO_SHOT = 1
        DAMAGE_BOOST = 2
        BOUNCE = 4
        RAILGUN = 8

# each powerup gives you approximately 1.4x more power
# but you also give something up
bullet_modifiers = [
    Weapon("two-shot",
        damage_multiplier=0.4,
        cooldown_multiplier=0.6,
        speed=1.3,
        shape=BulletShape.BULLET_SHAPE_TINY),
    Weapon("damage boost",
        damage_multiplier=1.6,
        cooldown_multiplier=3,
        speed=0.7,
        color=BulletColor.BULLET_COLOR_RED),
    Weapon("bounce",
        damage_multiplier=0.8,
        cooldown_multiplier=1.5),
    Weapon("railgun",
        damage_multiplier=1.2,
        cooldown_multiplier=1.2,
        cls=RailgunBullet),
    ]

weapon_matrix = []

for i in range(16):
    if i == 0:
        weapon = Weapon("normal")
    elif i == 15:
        weapon = Weapon("boss killer",
            damage_multiplier=20,
            cooldown_multiplier=5,
            cls=BossKillerBullet)
    else:
        weapon = Weapon("")
        names = []
        for bit, delta in enumerate(bullet_modifiers):
            if i & (1<<bit):
                names.append(delta.name)
                weapon.damage_multiplier *= delta.damage_multiplier
                weapon.cooldown_multiplier *= delta.cooldown_multiplier
                if delta.cls != Bullet:
                    weapon.cls = delta.cls
                if delta.color != BulletColor.BULLET_COLOR_WHITE:
                    weapon.color = delta.color
        assert names, f"names empty for i {i}"
        if len(names) == 1:
            weapon.name = names[0]
        elif len(names) == 2:
            weapon.name = f"{names[0]} and {names[1]}"
        else:
            weapon.name = ", ".join(names[:-1]) + ", and " + names[-1]

    weapon_matrix.append(weapon)


class Player:

    def __init__(self):
        self.cooldown_range = (10, 12)
        self.bullet_collision_filter = level.player_bullet_collision_filter
        self.bullet_collision_type = CollisionType.PLAYER_BULLET
        self.bullet_speed = 40
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

        self.health = 1000

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
        self.shape.elasticity = 0.0
        level.space.add(self.body, self.shape)
        self.trail = Trail(self, viewport, level)

        # self.ray = Ray(self.sprite.position, self.sprite.position, width=3, color=(1.0, 0.0, 0.0, 0.5))

    def toggle_weapon(self, bit):
        i = 1 << (bit - 1)
        if self.weapon_index & i:
            index = self.weapon_index & ~i
        else:
            index = self.weapon_index | i
        print(f"weapon changed from {self.weapon_index} to {index}")
        print(weapon_matrix[index])
        print()
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
        desired_velocity.rotate(reticle.theta)

        self.desired_velocity = desired_velocity
        self.acceleration = desired_velocity / self.acceleration_frames

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

    def on_player_moved(self):
        self.position = self.body.position
        sprite_coordinates = level.map_to_world(self.position)
        self.sprite.position = sprite_coordinates
        viewport.position = self.sprite.position
        player_light.position = self.body.position
        reticle.on_player_moved()

    def on_update_velocity(self, body, gravity, damping, dt):
        velocity = Vec2d(self.velocity)
        body.velocity = velocity
        self.body.velocity = velocity

    def on_update(self, dt):
        # TODO
        # actually use dt here
        # instead of assuming it's 1/60 of a second
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

    def on_draw(self):
        self.sprite.draw()

    def on_damage(self, damage):
        self.health -= damage
        if self.health <= 0:
            self.on_died()

    def on_died(self):
        game.paused = True


class Reticle:
    def __init__(self):
        self.image = pyglet.image.load("gfx/reticle.png")
        self.image.anchor_x = self.image.anchor_y = self.image.width // 2
        self.sprite = pyglet.sprite.Sprite(self.image, batch=level.bullet_batch, group=level.foreground_sprite_group)
        self.position = Vec2d(0, 0)
        # how many pixels movement onscreen map to one revolution
        self.acceleration = 3000
        self.mouse_multiplier = -(math.pi * 2) / self.acceleration
        # in radians
        self.theta = 0
        # in pymunk coordinates
        self.magnitude = 3
        self.offset = Vec2d(self.magnitude, 0)

    def on_mouse_motion(self, x, y, dx, dy):
        if dx:
            self.theta += dx * self.mouse_multiplier
            viewport.angle = self.theta
            self.offset = Vec2d(self.magnitude, 0)
            self.offset.rotate(self.theta)
            player.sprite.rotation = self.theta
            player.calculate_acceleration()
            self.on_player_moved()

    def on_mouse_drag(self, x, y, dx, dy, buttons, modifiers):
        return self.on_mouse_motion(x, y, dx, dy)

    def on_player_moved(self):
        self.position = Vec2d(player.position) + self.offset
        sprite_coordinates = level.map_to_world(self.position)
        self.sprite.set_position(*sprite_coordinates)

    def on_draw(self):
        pass
        # self.sprite.draw()


def is_moving(v):
    """Return True if a vector represents an object that is moving."""
    return v.get_length_sqrd() > 1e-3




robots = set()
shape_to_robot = {}



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
            ):
            class_method = getattr(self.__class__, callback_name)
            base_class_method = getattr(RobotBehaviour, callback_name)
            if class_method != base_class_method:
                callbacks = getattr(robot, callback_name + "_callbacks")
                callbacks.append(getattr(self, callback_name))

    def on_update(self, dt):
        pass

    def on_collision_wall(self, wall_shape):
        pass

    def on_damage(self, damage):
        pass

    def on_died(self):
        pass

robot_base_weapon = Weapon("robot base weapon",
    damage_multiplier=1,
    cooldown_multiplier=1,
    speed=1,
    color=BulletColor.BULLET_COLOR_WHITE,
    shape=BulletShape.BULLET_SHAPE_NORMAL,
    cls=Bullet)


class RobotShootConstantly(RobotBehaviour):
    cooldown = 0

    def on_update(self, dt):
        if self.cooldown > 0:
            self.cooldown -= 1
            return

        vector_to_player = Vec2d(player.position) - robot.position
        bullet = robot_base_weapon.fire(self.robot, vector_to_player)
        self.cooldown = bullet.cooldown



class RobotShootsOnlyWhenPlayerIsVisible(RobotBehaviour):
    cooldown = 0

    def on_update(self, dt):
        if self.cooldown > 0:
            self.cooldown -= 1
            return

        collision = level.space.segment_query_first(self.robot.position,
            player.position,
            player.radius / 3, # TODO this shouldn't be hard-coded
            level.robot_bullet_collision_filter)
        if collision and collision.shape == player.shape:
            vector_to_player = Vec2d(player.position) - robot.position
            bullet = robot_base_weapon.fire(self.robot, vector_to_player)
            self.cooldown = bullet.cooldown


class RobotMovesRandomly(RobotBehaviour):
    countdown = 0
    def __init__(self, robot):
        super().__init__(robot)
        # how many units per second
        self.speed = (1 + (random.random() * 2.5))

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


class RobotMovesStraightTowardsPlayer(RobotBehaviour):
    def __init__(self, robot):
        super().__init__(robot)
        # how many units per second
        self.speed = (1 + (random.random() * 2.5))

    # TODO if you have time: make it try to go around walls?
    # def on_collision_wall(self, wall_shape):
    #     self.pick_new_vector()

    def on_update(self, dt):
        vector = player.position - self.robot.position
        vector = vector.normalized() * self.speed
        self.robot.velocity = vector



class Robot:
    def __init__(self, position, evolution=0):
        # used only to calculate starting position of bullet
        self.radius = 0.7071067811865476
        self.bullet_collision_filter = level.robot_bullet_collision_filter
        self.bullet_collision_type = CollisionType.ROBOT_BULLET
        self.bullet_speed = 15

        self.position = Vec2d(position)
        self.velocity = Vec2d(0, 0)

        self.on_update_callbacks = []
        self.on_collision_wall_callbacks = []
        self.on_damage_callbacks = []
        self.on_died_callbacks = []

        self.health = 100
        self.cooldown_range = (180, 240)
        self.cooldown = 0

        self.sprite = EnemyRobotSprite(level.map_to_world(position), evolution)

        self.body = pymunk.Body(mass=1, moment=pymunk.inf, body_type=pymunk.Body.DYNAMIC)
        self.body.position = Vec2d(self.position)
        self.body.velocity_func = self.on_update_velocity

        # robots are square!
        self.shape = pymunk.Poly.create_box(self.body, (1, 1))
        self.shape.collision_type = CollisionType.ROBOT
        self.shape.filter = level.robot_collision_filter
        shape_to_robot[self.shape] = self
        level.space.add(self.body, self.shape)
        robots.add(self)

    def on_update_velocity(self, body, gravity, damping, dt):
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

    def close(self):
        robots.discard(self)
        level.space.remove(self.body, self.shape)
        self.sprite.delete()
        self.sprite = None


    def on_died(self):
        for fn in self.on_died_callbacks:
            if fn():
                return
        self.close()
        Kaboom(level.map_to_world(self.position))

    def on_collision_wall(self, wall_shape):
        for fn in self.on_collision_wall_callbacks:
            if fn(wall_shape):
                return


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
        '_start', '_end', '_width', 'vl',
    )

    def __init__(self, start, end, width=2.0, color=(1.0, 1.0, 1.0, 0.5)):
        self._start = Vec2d(start)
        self._end = Vec2d(end)
        self._width = width * 0.5
        self.vl = self.batch.add(
            4, gl.GL_QUADS, self.group,
            ('v2f/dynamic', (0, 0, 1, 0, 1, 1, 0, 1)),
            ('t2f/dynamic', (0, 0, 0, 1, 1, 1, 1, 0)),
            ('c4f/static', [comp for _ in range(4) for comp in color]),
        )
        self._recalculate()

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


game = Game()
# level = Level("prototype")
level = Level("level1")

RobotSprite.load()

reticle = Reticle()

player = Player()
player.on_player_moved()

robot = Robot(player.position + Vec2d(5, -5))
# RobotShootsConstantly(robot)
RobotShootsOnlyWhenPlayerIsVisible(robot)
# RobotMovesRandomly(robot)
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
    pyglet.app.exit()

@keypress(key.SPACE)
def key_escape(pressed):
    # print("SPACE", pressed)
    if pressed:
        game.paused = not game.paused
        window.set_exclusive_mouse(not game.paused)
        player.on_pause_change()

# @keypress(key.UP)
# def key_up(pressed):
#     print("UP", pressed)

# @keypress(key.DOWN)
# def key_down(pressed):
#     print("DOWN", pressed)

# @keypress(key.LEFT)
# def key_left(pressed):
#     print("LEFT", pressed)

# @keypress(key.RIGHT)
# def key_right(pressed):
#     print("RIGHT", pressed)

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
def on_mouse_motion(x, y, dx, dy):
    reticle.on_mouse_motion(x, y, dx, dy)

@window.event
def on_mouse_drag(x, y, dx, dy, buttons, modifiers):
    reticle.on_mouse_drag(x, y, dx, dy, buttons, modifiers)


LEFT_MOUSE_BUTTON = pyglet.window.mouse.LEFT

@window.event
def on_mouse_press(x, y, button, modifiers):
    if button == LEFT_MOUSE_BUTTON:
        player.shooting = True

@window.event
def on_mouse_release(x, y, button, modifiers):
    if button == LEFT_MOUSE_BUTTON:
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
            RobotSprite.draw_diffuse()
        RobotSprite.draw_emit()
        level.bullet_batch.draw()

        default_system.draw()
        Ray.draw()
    game.on_draw()
    # with debug_viewport:
    #     glScalef(8.0, 8.0, 8.0)
    #     level.space.debug_draw(level.draw_options)


def on_update(dt):
    if game.paused:
        return

    level.space.step(dt)
    # print()
    # print("PLAYER", player.body.position)
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

pyglet.clock.schedule_interval(on_update, 1/120.0)


# win = pyglet.window.Window(resizable=True, visible=False)
# win.clear()

def on_resize(width, height):
    """Setup 3D projection for window"""
    gl.glViewport(0, 0, width, height)
    gl.glMatrixMode(gl.GL_PROJECTION)
    gl.glLoadIdentity()
    gl.gluPerspective(70, 1.0*width/height, 0.1, 1000.0)
    gl.glMatrixMode(gl.GL_MODELVIEW)
    gl.glLoadIdentity()

    viewport.w = width
    viewport.h = height
# window.on_resize = on_resize

yrot = 0.0

MEAN_FIRE_INTERVAL = 3.0


pyglet.clock.schedule_interval(default_system.update, (1.0/30.0))
pyglet.clock.set_fps_limit(None)


pyglet.app.run()
