/*
Copyright (C) 2010-2014 GRNET S.A.

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <http://www.gnu.org/licenses/>.
 */

#ifndef _XLOCK_H
#define _XLOCK_H

#include <xseg/util.h>

#define MFENCE() __sync_synchronize()
#define BARRIER() __asm__ __volatile__ ("" ::: "memory")
#define __pause() __asm__ __volatile__ ("pause\n");
#undef __pause
#define __pause()

#define Noone ((unsigned long)-1)
#define XLOCK_UNKNOWN_OWNER ((unsigned long)-2)

#define XLOCK_SANITY_CHECKS
#define XLOCK_CONGESTION_NOTIFY

#ifdef XLOCK_SANITY_CHECKS
#define MAX_VALID_OWNER 65536 /* we are not gonna have more ports than that */
#endif /* XLOCK_SANITY_CHECKS */

#ifdef XLOCK_CONGESTION_NOTIFY
#define MIN_SHIFT 20
#define MAX_SHIFT ((sizeof(unsigned long) * 8) -1)
#endif /* XLOCK_CONGESTION_NOTIFY */

struct xlock {
	unsigned long owner;
};
//} __attribute__ ((aligned (16))); /* support up to 128bit longs */

#ifdef XLOCK_SANITY_CHECKS
static inline int __is_valid_owner(unsigned long owner)
{
	if (owner == XLOCK_UNKNOWN_OWNER || owner <= MAX_VALID_OWNER)
		return 1;
	return 0;
}
#endif /* XLOCK_SANITY_CHECKS */

static inline unsigned long xlock_acquire(struct xlock *lock, unsigned long who)
{
	unsigned long owner;
#ifdef XLOCK_CONGESTION_NOTIFY
	unsigned long times = 1;
	unsigned long shift = MIN_SHIFT;
#endif /* XLOCK_CONGESTION_NOTIFY */

	for (;;) {
		for (; (owner = *(volatile unsigned long *)(&lock->owner) != Noone);){
#ifdef XLOCK_SANITY_CHECKS
			if (!__is_valid_owner(owner)) {
				XSEGLOG("xlock %lx corrupted. Lock owner %lu",
						(unsigned long) lock, owner);
				XSEGLOG("Resetting xlock %lx to Noone", 
						(unsigned long) lock);
				lock->owner = Noone;
			}
#endif /* XLOCK_SANITY_CHECKS */
#ifdef XLOCK_CONGESTION_NOTIFY
			if (!(times & ((1<<shift) -1))){
				XSEGLOG("xlock %lx spinned for %llu times"
					"\n\t who: %lu, owner: %lu",
					(unsigned long) lock, times,
					who, owner);
				if (shift < MAX_SHIFT)
					shift++;
//				xseg_printtrace();
			}
			times++;
#endif /* XLOCK_CONGESTION_NOTIFY */
			__pause();
		}

		if (__sync_bool_compare_and_swap(&lock->owner, Noone, who))
			break;
	}
#ifdef XLOCK_SANITY_CHECKS
	if (!__is_valid_owner(lock->owner)) {
		XSEGLOG("xlock %lx locked with INVALID lock owner %lu",
				(unsigned long) lock, lock->owner);
	}
#endif /* XLOCK_SANITY_CHECKS */

	return who;
}

static inline unsigned long xlock_try_lock(struct xlock *lock, unsigned long who)
{
	unsigned long owner;
	owner = *(volatile unsigned long *)(&lock->owner);
	if (owner == Noone)
		return __sync_bool_compare_and_swap(&lock->owner, Noone, who);
	return 0;
}

static inline void xlock_release(struct xlock *lock)
{
	BARRIER();
	/*
#ifdef XLOCK_SANITY_CHECKS
	if (!__is_valid_owner(lock->owner)) {
		XSEGLOG("xlock %lx releasing lock with INVALID lock owner %lu",
				(unsigned long) lock, lock->owner);
	}
#endif 
	*/
	/* XLOCK_SANITY_CHECKS */
	lock->owner = Noone;
}

static inline unsigned long xlock_get_owner(struct xlock *lock)
{
	return *(volatile unsigned long *)(&lock->owner);
}

#endif
