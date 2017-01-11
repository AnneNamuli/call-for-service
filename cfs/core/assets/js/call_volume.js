import "leaflet/dist/leaflet.css";

import {
    Page,
    buildURL,
    monitorChart
} from "./core";
import {
    HorizontalBarChart,
    DiscreteBarChart,
    Heatmap,
    RegionMap
} from "./charts";
import _ from "underscore-contrib";
import d3 from "d3";
import colorbrewer from "colorbrewer";
import nv from "nvd3";

var callVolumeURL = "/api/" + agencyCode + "/call_volume/";

var outFormats = {
    "month": "%b %Y",
    "week": "%m/%d/%y",
    "day": "%a %m/%d",
    "hour": "%m/%d %H:%M"
};

var dashboard = new Page({
    el: document.getElementById("dashboard"),
    template: require("../templates/call_volume.html"),
    data: {
        mapDrawn: false,
        "capitalize": function (string) {
            return string.charAt(0).toUpperCase() + string.slice(1);
        },
        config: siteConfig,
        data: {
            "volume_over_time": {
                "period_size": "day",
                "results": []
            },
            "day_hour_heatmap": [],
            "volume_by_source": {}
        }
    },
    filterUpdated: function (filter) {
        d3.json(
            buildURL(callVolumeURL, filter), _.bind(
                function (error, newData) {
                    if (error) throw error;
                    this.set("loading", false);
                    this.set("initialload", false);
                    newData = cleanupData(newData);
                    this.set("data", newData);
                }, this));
    }
});


function cleanupData(data) {
    var indate = d3.time.format("%Y-%m-%dT%H:%M:%S");

    data.volume_by_nature_group = _.chain(data.volume_by_nature_group)
        .filter(function (d) {
            return d.name;
        })
        .sortBy(function (d) {
            return d.name;
        })
        .value();
    data.volume_by_nature_group = [{
        key: "Call Volume",
        values: data.volume_by_nature_group
    }];

    data.volume_by_nature = _.chain(data.volume_by_nature)
        .filter(function (d) {
            return d.name;
        })
        .sortBy(function (d) {
            return -d.volume;
        })
        .first(20)
        .value();
    data.volume_by_nature = [{
        key: "Call Volume",
        values: data.volume_by_nature
    }];

    data.volume_by_date = [{
        key: "Call Volume",
        values: _.map(
            data.volume_by_date,
            function (obj) {
                obj = _.chain(obj)
                    .selectKeys(["date", "volume"])
                    .renameKeys({
                        "date": "x",
                        "volume": "y"
                    })
                    .value();
                obj.x = indate.parse(obj.x);
                return obj;
            })
    }];

    var sources = ["Officer", "Citizen"];

    data.volume_by_source = _.chain(data.volume_by_source).map(function (d) {
        return {
            id: d.id,
            volume: d.volume,
            name: sources[d.id]
        };
    }).sortBy(function (d) {
        return d.id;
    }).value();

    data.volume_by_source = [{
        key: "Volume by Source",
        values: data.volume_by_source
    }];

    if (siteConfig.use_beat) {
        data.map_data = _.reduce(
            data.volume_by_beat,
            function (memo, d) {
                memo[d.name] = d.volume;
                return memo;
            }, {});
    } else if (siteConfig.use_district) {
        data.map_data = _.reduce(
            data.volume_by_district,
            function (memo, d) {
                memo[d.name] = d.volume;
                return memo;
            }, {});
    }

    data.volume_by_beat = [{
        key: "Volume By Beat",
        values: _.chain(data.volume_by_beat)
            .filter(
                function (d) {
                    return d.name;
                })
            .sortBy(
                function (d) {
                    return d.volume;
                })
            .value()
    }];

    var dow = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
    data.volume_by_dow = [{
        key: "Volume By Day of Week",
        values: _.chain(data.volume_by_dow)
            .map(function (d) {
                return {
                    id: d.id,
                    volume: d.volume,
                    name: dow[d.id]
                };
            })
            .sortBy(
                function (d) {
                    return d.id;
                })
            .value()
    }];

    var shifts = ["Shift 1", "Shift 2"];
    data.volume_by_shift = [{
        key: "Volume By Shift",
        values: _.chain(data.volume_by_shift)
            .map(function (d) {
                return {
                    id: d.id,
                    volume: d.volume,
                    name: shifts[d.id]
                };
            })
            .sortBy(
                function (d) {
                    return d.id;
                })
            .value()
    }];

    var heatmapData = _.map(data.heatmap,
        function (d) {
            return {
                day: +d.dow_received,
                hour: +d.hour_received,
                value: +d.volume
            };
        }
    );

    if (heatmapData.length > 0 && heatmapData.length < 24 * 7) {
        var findData = function (day, hour) {
            return function (d) {
                return d.day === day && d.hour === hour;
            };
        };
        for (var i = 0; i < 7; i++) {
            for (var j = 0; j < 24; j++) {
                if (!_.find(heatmapData, findData(i, j))) {
                    heatmapData.push({
                        day: i,
                        hour: j
                    });
                }
            }
        }
    }

    heatmapData = _.sortBy(heatmapData, function (d) {
        return d.day * 24 + d.hour;
    });

    data.heatmap = heatmapData;

    return data;
}


// ========================================================================
// Functions
// ========================================================================

var volumeByDOWChart = new HorizontalBarChart({
    el: "#volume-by-dow",
    filter: "dow_received",
    ratio: 1.5,
    dashboard: dashboard,
    fmt: d3.format(",d"),
    x: function (d) {
        return d.name;
    },
    y: function (d) {
        return d.volume;
    }
});

monitorChart(dashboard, "data.volume_by_dow", volumeByDOWChart.update);


if (siteConfig.use_shift) {
    var volumeByShiftChart = new HorizontalBarChart({
        el: "#volume-by-shift",
        filter: "shift",
        ratio: 2.5,
        dashboard: dashboard,
        fmt: d3.format(",d"),
        x: function (d) {
            return d.name;
        },
        y: function (d) {
            return d.volume;
        }
    });

    monitorChart(dashboard, "data.volume_by_shift", volumeByShiftChart.update);
}


var volumeByNatureGroupChart = null;
if (siteConfig.use_nature_group) {
    volumeByNatureGroupChart = new DiscreteBarChart({
        el: "#volume-by-nature",
        dashboard: dashboard,
        filter: "nature__nature_group",
        ratio: 2,
        rotateLabels: true,
        fmt: d3.format(",d"),
        x: function (d) {
            return d.name;
        },
        y: function (d) {
            return d.volume;
        }
    });

    monitorChart(dashboard, "data.volume_by_nature_group", volumeByNatureGroupChart.update);
} else if (siteConfig.use_nature) {
    volumeByNatureGroupChart = new DiscreteBarChart({
        el: "#volume-by-nature",
        dashboard: dashboard,
        filter: "nature",
        ratio: 2,
        rotateLabels: true,
        fmt: d3.format(",d"),
        x: function (d) {
            return d.name;
        },
        y: function (d) {
            return d.volume;
        }
    });

    monitorChart(dashboard, "data.volume_by_nature", volumeByNatureGroupChart.update);
}

if (siteConfig.use_call_source) {
    var volumeBySourceChart = new HorizontalBarChart({
        el: "#volume-by-source",
        filter: "initiated_by",
        ratio: 2.5,
        dashboard: dashboard,
        fmt: d3.format(",d"),
        x: function (d) {
            return d.name;
        },
        y: function (d) {
            return d.volume;
        }
    });

    monitorChart(dashboard, "data.volume_by_source", volumeBySourceChart.update);
}

if (siteConfig.use_beat || siteConfig.use_district) {
    const region = siteConfig.use_beat
          ? 'beat'
          : 'district';

    var volumeMap = new RegionMap({
        el: "#map",
        dashboard: dashboard,
        colorScheme: colorbrewer.Blues,
        format: function (val) {
            return d3.format(",.2f")(val).replace(/\.0+$/, "");
        },
        dataDescr: "Call Volume",
        region: region
    });

    monitorChart(dashboard, "data.map_data", volumeMap.update);
}


var heatmap = new Heatmap({
    el: "#heatmap",
    dashboard: dashboard,
    colors: colorbrewer.Blues[5],
    fmt: function (val) {
        return d3.format(",.2f")(val).replace(/\.0+$/, "");
    },
    measureName: "calls"
});

monitorChart(dashboard, "data.heatmap", heatmap.update);


function buildVolumeByDateChart(data) {
    var container = d3.select("#volume-by-date");
    var parentWidth = container.node().clientWidth;
    var width = parentWidth;
    var height = width / 2.5;

    var svg = d3.select("#volume-by-date svg");
    svg.attr("width", width)
        .attr("height", height)
        .style("height", height + "px")
        .style("width", width + "px");

    var resize = function (chart) {
        width = container.node().clientWidth;
        height = Math.ceil(width / 2.5);

        container.select("svg")
            .attr("width", width)
            .attr("height", height)
            .style("height", height + "px")
            .style("width", width + "px");

        chart.height(height).width(width);

        chart.update();
    };

    nv.addGraph(
        function () {
            var chart = nv.models.lineChart()
                .options({
                    height: height,
                    width: width,
                    margin: {
                        "right": 60
                    },
                    transitionDuration: 300,
                    useInteractiveGuideline: true,
                    forceY: [0],
                    showLegend: false
                });

            chart.xAxis
                .tickFormat(
                    function (d) {
                        return d3.time.format(outFormats[dashboard.get("data.precision")])(
                            new Date(d));
                        //return d3.time.format('%x')(new Date(d));
                    });

            chart.yAxis
                .axisLabel("Volume")
                .tickFormat(d3.format(",d"));

            svg.datum(data).call(chart);
            nv.utils.windowResize(function () {
                resize(chart);
            });
            return chart;
        });
}

monitorChart(dashboard, "data.volume_by_date", buildVolumeByDateChart);
