#!/usr/bin/env python

# Copyright 2012 GRNET S.A. All rights reserved.
#
# Redistribution and use in source and binary forms, with or
# without modification, are permitted provided that the following
# conditions are met:
#
#   1. Redistributions of source code must retain the above
#      copyright notice, this list of conditions and the following
#      disclaimer.
#   2. Redistributions in binary form must reproduce the above
#      copyright notice, this list of conditions and the following
#      disclaimer in the documentation and/or other materials
#      provided with the distribution.
#
# THIS SOFTWARE IS PROVIDED BY GRNET S.A. ``AS IS'' AND ANY EXPRESS
# OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
# WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR
# PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL GRNET S.A OR
# CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
# SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
# LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF
# USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED
# AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT
# LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN
# ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.
#
# The views and conclusions contained in the software and
# documentation are those of the authors and should not be
# interpreted as representing official policies, either expressed
# or implied, of GRNET S.A.
#


import os, sys, subprocess, argparse, time, psutil, signal, errno
from struct import unpack
from binascii import hexlify

from .common import *

@exclusive
def showmapped(args):
    try:
        devices = os.listdir(os.path.join(XSEGBD_SYSFS, "devices/"))
    except:
        if loaded_module(xsegbd):
            raise Error("Cannot list %s/devices/" % XSEGBD_SYSFS)
        else:
            return 0

    print "id\tpool\timage\tsnap\tdevice"
    if not devices:
        print "No volumes mapped\n"
        return 0
    try:
        for f in devices:
            d_id = open(XSEGBD_SYSFS + "devices/" + f + "/id").read().strip()
            target = open(XSEGBD_SYSFS + "devices/"+ f + "/target").read().strip()

            print "%s\t%s\t%s\t%s\t%s" % (d_id, '-', target, '-', DEVICE_PREFIX +
            d_id)
    except Exception, reason:
        raise Error(reason)
    return len(devices)

def showmapped_wrapper(args):
    showmapped(args)


@exclusive
def create(args):
    name = args.name[0]
    size = args.size
    snap = args.snap

    if len(name) < 6:
        raise Error("Name should have at least len 6")
    if size == None and snap == None:
        raise Error("At least one of the size/snap args must be provided")

    ret = False
    xseg_ctx = Xseg_ctx(config['SPEC'], config['VTOOL'])
    with Request(xseg_ctx, config['MPORT'], len(name), sizeof(xseg_request_clone)) as req:
        req.set_op(X_CLONE)
        req.set_size(sizeof(xseg_request_clone))
        req.set_offset(0)
        req.set_target(name)

        xclone = xseg_request_clone()
        if snap:
            xclone.target = snap
            xclone.targetlen = len(snap)
        else:
            xclone.target = ""
            xclone.targetlen = 0
        if size:
            xclone.size = size << 20
        else:
            xclone.size = -1

        req.set_data(xclone)
        req.submit()
        req.wait()
        ret = req.success()
    xseg_ctx.shutdown()
    if not ret:
        raise Error("vlmc creation failed")

@exclusive
def snapshot(args):
    # snapshot
    name = args.name[0]

    if len(name) < 6:
        raise Error("Name should have at least len 6")

    ret = False
    xseg_ctx = Xseg_ctx(config['SPEC'], config['VTOOL'])
    with Request(xseg_ctx, config['VPORT_START'], len(name), sizeof(xseg_request_snapshot)) as req:
        req.set_op(X_SNAPSHOT)
        req.set_size(sizeof(xseg_request_snapshot))
        req.set_offset(0)
        req.set_target(name)

        xsnapshot = xseg_request_snapshot()
        xsnapshot.target = ""
        xsnapshot.targetlen = 0
        req.set_data(xsnapshot)
        req.submit()
        req.wait()
        ret = req.success()
        if ret:
            reply = string_at(req.get_data(xseg_reply_snapshot).contents.target, 64)
    xseg_ctx.shutdown()
    if not ret:
        raise Error("vlmc snapshot failed")
    sys.stdout.write("Snapshot name: %s\n" % reply)


def list_volumes(args):
    if config['STORAGE'] == "rados":
        import rados
        cluster = rados.Rados(conffile=config['CEPH_CONF_FILE'])
        cluster.connect()
        ioctx = cluster.open_ioctx(config['RADOS_POOL_MAPS'])
        oi = rados.ObjectIterator(ioctx)
        for o in oi :
            name = o.key
            if name.startswith(ARCHIP_PREFIX) and not name.endswith('_lock'):
		    print name[len(ARCHIP_PREFIX):]
    elif config['STORAGE'] == "files":
        raise Error("Vlmc list not supported for files yet")
    else:
        raise Error("Invalid storage")


@exclusive
def remove(args):
    name = args.name[0]

    try:
        for f in os.listdir(XSEGBD_SYSFS + "devices/"):
            d_id = open(XSEGBD_SYSFS + "devices/" + f + "/id").read().strip()
            target = open(XSEGBD_SYSFS + "devices/"+ f + "/target").read().strip()
            if target == name:
                raise Error("Volume mapped on device %s%s" % (DEVICE_PREFIX,
								d_id))

    except Exception, reason:
        raise Error(name + ': ' + str(reason))

    ret = False
    xseg_ctx = Xseg_ctx(config['SPEC'], config['VTOOL'])
    with Request(xseg_ctx, config['MPORT'], len(name), 0) as req:
        req.set_op(X_DELETE)
        req.set_size(0)
        req.set_offset(0)
        req.set_target(name)
        req.submit()
        req.wait()
        ret = req.success()
    xseg_ctx.shutdown()
    if not ret:
        raise Error("vlmc removal failed")


@exclusive
def map_volume(args):
    if not loaded_module(xsegbd):
        raise Error("Xsegbd module not loaded")
    name = args.name[0]
    prev = config['XSEGBD_START']
    try:
        result = [int(open(XSEGBD_SYSFS + "devices/" + f + "/srcport").read().strip()) for f in os.listdir(XSEGBD_SYSFS + "devices/")]
        result.sort()

        for p in result:
            if p - prev > 1:
               break
            else:
               prev = p

        port = prev + 1
        if port > config['XSEGBD_END']:
            raise Error("Max xsegbd devices reached")
        fd = os.open(XSEGBD_SYSFS + "add", os.O_WRONLY)
        print >> sys.stderr, "write to %s : %s %d:%d:%d" %( XSEGBD_SYSFS +
			"add", name, port, port - config['XSEGBD_START'] + config['VPORT_START'], REQS )
        os.write(fd, "%s %d:%d:%d" % (name, port, port - config['XSEGBD_START']
                                                    + config['VPORT_START'], REQS))
        os.close(fd)
    except Exception, reason:
        raise Error(name + ': ' + str(reason))

@exclusive
def unmap_volume(args):
    if not loaded_module(xsegbd):
        raise Error("Xsegbd module not loaded")
    device = args.name[0]
    try:
        for f in os.listdir(XSEGBD_SYSFS + "devices/"):
            d_id = open(XSEGBD_SYSFS + "devices/" + f + "/id").read().strip()
            name = open(XSEGBD_SYSFS + "devices/"+ f + "/target").read().strip()
            if device == DEVICE_PREFIX + d_id:
                fd = os.open(XSEGBD_SYSFS + "remove", os.O_WRONLY)
                os.write(fd, d_id)
                os.close(fd)
                return
        raise Error("Device %s doesn't exist" % device)
    except Exception, reason:
        raise Error(device + ': ' + str(reason))

# FIXME:
def resize(args):
    if not loaded_module(xsegbd):
        raise Error("Xsegbd module not loaded")

    name = args.name[0]
    size = args.size[0]

    try:

        for f in os.listdir(XSEGBD_SYSFS + "devices/"):
            d_id = open(XSEGBD_SYSFS + "devices/" + f + "/id").read().strip()
            d_name = open(XSEGBD_SYSFS + "devices/"+ f + "/name").read().strip()
            if name == d_name:
                fd = os.open(XSEGBD_SYSFS + "devices/" +  d_id +"/refresh", os.O_WRONLY)
                os.write(fd, "1")
                os.close(fd)

    except Exception, reason:
        raise Error(name + ': ' + str(reason))

@exclusive
def lock(args):
    name = args.name[0]

    if len(name) < 6:
        raise Error("Name should have at least len 6")

    name = ARCHIP_PREFIX + name

    ret = False
    xseg_ctx = Xseg_ctx(config['SPEC'], config['VTOOL'])
    with Request(xseg_ctx, config['MBPORT'], len(name), 0) as req:
        req.set_op(X_ACQUIRE)
        req.set_size(0)
        req.set_offset(0)
        req.set_flags(XF_NOSYNC)
        req.set_target(name)
        req.submit()
        req.wait()
        ret = req.success()
    xseg_ctx.shutdown()
    if not ret:
        raise Error("vlmc lock failed")
    else:
        sys.stdout.write("Volume locked\n")

@exclusive
def unlock(args):
    name = args.name[0]
    force = args.force

    if len(name) < 6:
        raise Error("Name should have at least len 6")

    name = ARCHIP_PREFIX + name

    ret = False
    xseg_ctx = Xseg_ctx(config['SPEC'], config['VTOOL'])
    with Request(xseg_ctx, config['MBPORT'], len(name), 0) as req:
        req.set_op(X_RELEASE)
        req.set_size(0)
        req.set_offset(0)
        req.set_target(name)
        if force:
            req.set_flags(XF_NOSYNC|XF_FORCE)
        else:
            req.set_flags(XF_NOSYNC)
        req.submit()
        req.wait()
        ret = req.success()
    xseg_ctx.shutdown()
    if not ret:
        raise Error("vlmc unlock failed")
    else:
        sys.stdout.write("Volume unlocked\n")

@exclusive
def open_volume(args):
    name = args.name[0]

    if len(name) < 6:
        raise Error("Name should have at least len 6")

    ret = False
    xseg_ctx = Xseg_ctx(config['SPEC'], config['VTOOL'])
    with Request(xseg_ctx, config['VPORT_START'], len(name), 0) as req:
        req.set_op(X_OPEN)
        req.set_size(0)
        req.set_offset(0)
        req.set_target(name)
        req.submit()
        req.wait()
        ret = req.success()
    xseg_ctx.shutdown()
    if not ret:
        raise Error("vlmc open failed")
    else:
        sys.stdout.write("Volume opened\n")

@exclusive
def close_volume(args):
    name = args.name[0]

    if len(name) < 6:
        raise Error("Name should have at least len 6")

    ret = False
    xseg_ctx = Xseg_ctx(config['SPEC'], config['VTOOL'])
    with Request(xseg_ctx, config['VPORT_START'], len(name), 0) as req:
        req.set_op(X_CLOSE)
        req.set_size(0)
        req.set_offset(0)
        req.set_target(name)
        req.submit()
        req.wait()
        ret = req.success()
    xseg_ctx.shutdown()
    if not ret:
        raise Error("vlmc close failed")
    else:
        sys.stdout.write("Volume closed\n")

@exclusive
def info(args):
    name = args.name[0]

    if len(name) < 6:
        raise Error("Name should have at least len 6")

    ret = False
    xseg_ctx = Xseg_ctx(config['SPEC'], config['VTOOL'])
    with Request(xseg_ctx, config['MPORT'], len(name), 0) as req:
        req.set_op(X_INFO)
        req.set_size(0)
        req.set_offset(0)
        req.set_target(name)
        req.submit()
        req.wait()
        ret = req.success()
        if ret:
            size = req.get_data(xseg_reply_info).contents.size
    xseg_ctx.shutdown()
    if not ret:
        raise Error("vlmc info failed")
    else:
        sys.stdout.write("Volume %s: size: %d\n" % (name, size) )

def mapinfo(args):
    name = args.name[0]

    if len(name) < 6:
        raise Error("Name should have at least len 6")

    if STORAGE == "rados":
        import rados
        cluster = rados.Rados(conffile=config['CEPH_CONF_FILE'])
        cluster.connect()
        ioctx = cluster.open_ioctx(config['RADOS_POOL_MAPS'])
        BLOCKSIZE = 4*1024*1024
        try:
            mapdata = ioctx.read(ARCHIP_PREFIX + name, length=BLOCKSIZE)
        except Exception:
            raise Error("Cannot read map data")
        if not  mapdata:
            raise Error("Cannot read map data")
        pos = 0
        size_uint32t = sizeof(c_uint32)
        version = unpack("<L", mapdata[pos:pos+size_uint32t])[0]
        pos += size_uint32t
        size_uint64t = sizeof(c_uint64)
        size = unpack("Q", mapdata[pos:pos+size_uint64t])[0]
        pos += size_uint64t
        blocks = size / BLOCKSIZE
        nr_exists = 0
        print ""
        print "Volume: " + name
        print "Version: " + str(version)
        print "Size: " + str(size)
        for i in range(blocks):
            exists = bool(unpack("B", mapdata[pos:pos+1])[0])
            if exists:
                nr_exists += 1
            pos += 1
            block = hexlify(mapdata[pos:pos+32])
            pos += 32
            if args.verbose:
                print block, exists
        print "Actual disk usage: " + str(nr_exists * BLOCKSIZE),
        print '(' + str(nr_exists) + '/' + str(blocks) + ' blocks)'

    elif STORAGE=="files":
        raise Error("Mapinfo for file storage not supported")
    else:
        raise Error("Invalid storage")

