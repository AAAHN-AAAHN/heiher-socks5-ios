/* Bind the common meter around an unchanged inherited UDP fixture. Keep task
 * headers out: the fixture defines its I/O substitutions before including them. */
#ifndef STATISTICS_UDP_FIXTURE_MAIN_H
#define STATISTICS_UDP_FIXTURE_MAIN_H

int hev_meter_prepare (void);
int hev_meter_worker_enter (void);
void hev_meter_worker_leave (void);
int statistics_udp_fixture_main (void);

int
main (void)
{
    int result;
    if (hev_meter_prepare () < 0 || hev_meter_worker_enter () < 0)
        return 1;
    result = statistics_udp_fixture_main ();
    hev_meter_worker_leave ();
    return result;
}

#define main statistics_udp_fixture_main
#endif
