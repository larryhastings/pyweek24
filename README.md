My Sincere Apologies
====================

A game of fun, shooting, and I'm sorry to put you through this


A fabricator robot on Mars was supposed to make a bunch of
robots!  But it got lazy and made robots that could make
other robots.  And it made them smarter than they should have
been.  Now they've all gone off and hidden away in various
tanks and computers.

Happily, he knew how to construct *you*, a simple fighting
robot.  It's your job to clean out each area!


Written by Daniel Pope and Larry Hastings
for PyWeek #24.
Copyright 2017 Daniel Pope and Larry Hastings.


Requirements
------------

Check the requirements.txt for all the Python packages
you'll need.

You'll also need AVBin for Pyglet.  You can get that here:
    http://avbin.github.io/AVbin/Download.html


Controls
--------

W A S D moves (strafes)

Move mouse left-right to rotate

Left mouse button to fire

1 2 3 4 activates and deactivates powerups (see below)

Space to pause

Esc to quit


Powerups
--------

There are four powerups in the game.
You'll find them as blue tiles on the ground--
just run over them to pick them up.

Once you've got a powerup, you have it available
for the rest of the game.  But you don't have
to have it on all the time!  You can press
a number key to activate or deactivate a powerup:

    1 = triple shot
    2 = damage boost shot
    3 = bouncy shot
    4 = railgun shot

And you can even mix and match!  Turn on
only 1 and 4 to activate triple railgun shots!

Different powerups will have different
combined effects.  For example, damage
boost needs more cooldown time, and the
shots move more slowly too.  Triple shot
fires more quickly but the shots are much
less powerful

Once you get all four powerups,
if you turn them all on at once, you get
a special weapon just for the end-game
boss...!


Your HUD
--------

Along the left shows your current active powerups,
with a number to remind you of the correct key.

On the right is your current health.  Above that
are indicators for how many lives you have left.

You start with 5 lives.  Good luck!
