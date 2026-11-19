-- Generated from official Jellyfin 10.11.8, with no user data.
CREATE TABLE "AccessSchedules" (
    "Id" INTEGER NOT NULL CONSTRAINT "PK_AccessSchedules" PRIMARY KEY AUTOINCREMENT,
    "UserId" TEXT NOT NULL,
    "DayOfWeek" INTEGER NOT NULL,
    "StartHour" REAL NOT NULL,
    "EndHour" REAL NOT NULL,
    CONSTRAINT "FK_AccessSchedules_Users_UserId" FOREIGN KEY ("UserId") REFERENCES "Users" ("Id") ON DELETE CASCADE
);
CREATE TABLE "ActivityLogs" (
    "Id" INTEGER NOT NULL CONSTRAINT "PK_ActivityLogs" PRIMARY KEY AUTOINCREMENT,
    "Name" TEXT NOT NULL,
    "Overview" TEXT NULL,
    "ShortOverview" TEXT NULL,
    "Type" TEXT NOT NULL,
    "UserId" TEXT NOT NULL,
    "ItemId" TEXT NULL,
    "DateCreated" TEXT NOT NULL,
    "LogSeverity" INTEGER NOT NULL,
    "RowVersion" INTEGER NOT NULL
);
CREATE TABLE "AncestorIds" (
    "ItemId" TEXT NOT NULL,
    "ParentItemId" TEXT NOT NULL,
    CONSTRAINT "PK_AncestorIds" PRIMARY KEY ("ItemId", "ParentItemId"),
    CONSTRAINT "FK_AncestorIds_BaseItems_ItemId" FOREIGN KEY ("ItemId") REFERENCES "BaseItems" ("Id") ON DELETE CASCADE,
    CONSTRAINT "FK_AncestorIds_BaseItems_ParentItemId" FOREIGN KEY ("ParentItemId") REFERENCES "BaseItems" ("Id") ON DELETE CASCADE
);
CREATE TABLE "ApiKeys" (
    "Id" INTEGER NOT NULL CONSTRAINT "PK_ApiKeys" PRIMARY KEY AUTOINCREMENT,
    "DateCreated" TEXT NOT NULL,
    "DateLastActivity" TEXT NOT NULL,
    "Name" TEXT NOT NULL,
    "AccessToken" TEXT NOT NULL
);
CREATE TABLE "AttachmentStreamInfos" (
    "ItemId" TEXT NOT NULL,
    "Index" INTEGER NOT NULL,
    "Codec" TEXT NULL,
    "CodecTag" TEXT NULL,
    "Comment" TEXT NULL,
    "Filename" TEXT NULL,
    "MimeType" TEXT NULL,
    CONSTRAINT "PK_AttachmentStreamInfos" PRIMARY KEY ("ItemId", "Index"),
    CONSTRAINT "FK_AttachmentStreamInfos_BaseItems_ItemId" FOREIGN KEY ("ItemId") REFERENCES "BaseItems" ("Id") ON DELETE CASCADE
);
CREATE TABLE "BaseItemImageInfos" (
    "Id" TEXT NOT NULL CONSTRAINT "PK_BaseItemImageInfos" PRIMARY KEY,
    "Blurhash" BLOB NULL,
    "DateModified" TEXT NULL,
    "Height" INTEGER NOT NULL,
    "ImageType" INTEGER NOT NULL,
    "ItemId" TEXT NOT NULL,
    "Path" TEXT NOT NULL,
    "Width" INTEGER NOT NULL,
    CONSTRAINT "FK_BaseItemImageInfos_BaseItems_ItemId" FOREIGN KEY ("ItemId") REFERENCES "BaseItems" ("Id") ON DELETE CASCADE
);
CREATE TABLE "BaseItemMetadataFields" (
    "Id" INTEGER NOT NULL,
    "ItemId" TEXT NOT NULL,
    CONSTRAINT "PK_BaseItemMetadataFields" PRIMARY KEY ("Id", "ItemId"),
    CONSTRAINT "FK_BaseItemMetadataFields_BaseItems_ItemId" FOREIGN KEY ("ItemId") REFERENCES "BaseItems" ("Id") ON DELETE CASCADE
);
CREATE TABLE "BaseItemProviders" (
    "ItemId" TEXT NOT NULL,
    "ProviderId" TEXT NOT NULL,
    "ProviderValue" TEXT NOT NULL,
    CONSTRAINT "PK_BaseItemProviders" PRIMARY KEY ("ItemId", "ProviderId"),
    CONSTRAINT "FK_BaseItemProviders_BaseItems_ItemId" FOREIGN KEY ("ItemId") REFERENCES "BaseItems" ("Id") ON DELETE CASCADE
);
CREATE TABLE "BaseItemTrailerTypes" (
    "Id" INTEGER NOT NULL,
    "ItemId" TEXT NOT NULL,
    CONSTRAINT "PK_BaseItemTrailerTypes" PRIMARY KEY ("Id", "ItemId"),
    CONSTRAINT "FK_BaseItemTrailerTypes_BaseItems_ItemId" FOREIGN KEY ("ItemId") REFERENCES "BaseItems" ("Id") ON DELETE CASCADE
);
CREATE TABLE "BaseItems" (
    "Id" TEXT NOT NULL CONSTRAINT "PK_BaseItems" PRIMARY KEY,
    "Album" TEXT NULL,
    "AlbumArtists" TEXT NULL,
    "Artists" TEXT NULL,
    "Audio" INTEGER NULL,
    "ChannelId" TEXT NULL,
    "CleanName" TEXT NULL,
    "CommunityRating" REAL NULL,
    "CriticRating" REAL NULL,
    "CustomRating" TEXT NULL,
    "Data" TEXT NULL,
    "DateCreated" TEXT NULL,
    "DateLastMediaAdded" TEXT NULL,
    "DateLastRefreshed" TEXT NULL,
    "DateLastSaved" TEXT NULL,
    "DateModified" TEXT NULL,
    "EndDate" TEXT NULL,
    "EpisodeTitle" TEXT NULL,
    "ExternalId" TEXT NULL,
    "ExternalSeriesId" TEXT NULL,
    "ExternalServiceId" TEXT NULL,
    "ExtraIds" TEXT NULL,
    "ExtraType" INTEGER NULL,
    "ForcedSortName" TEXT NULL,
    "Genres" TEXT NULL,
    "Height" INTEGER NULL,
    "IndexNumber" INTEGER NULL,
    "InheritedParentalRatingSubValue" INTEGER NULL,
    "InheritedParentalRatingValue" INTEGER NULL,
    "IsFolder" INTEGER NOT NULL,
    "IsInMixedFolder" INTEGER NOT NULL,
    "IsLocked" INTEGER NOT NULL,
    "IsMovie" INTEGER NOT NULL,
    "IsRepeat" INTEGER NOT NULL,
    "IsSeries" INTEGER NOT NULL,
    "IsVirtualItem" INTEGER NOT NULL,
    "LUFS" REAL NULL,
    "MediaType" TEXT NULL,
    "Name" TEXT NULL,
    "NormalizationGain" REAL NULL,
    "OfficialRating" TEXT NULL,
    "OriginalTitle" TEXT NULL,
    "Overview" TEXT NULL,
    "OwnerId" TEXT NULL,
    "ParentId" TEXT NULL,
    "ParentIndexNumber" INTEGER NULL,
    "Path" TEXT NULL,
    "PreferredMetadataCountryCode" TEXT NULL,
    "PreferredMetadataLanguage" TEXT NULL,
    "PremiereDate" TEXT NULL,
    "PresentationUniqueKey" TEXT NULL,
    "PrimaryVersionId" TEXT NULL,
    "ProductionLocations" TEXT NULL,
    "ProductionYear" INTEGER NULL,
    "RunTimeTicks" INTEGER NULL,
    "SeasonId" TEXT NULL,
    "SeasonName" TEXT NULL,
    "SeriesId" TEXT NULL,
    "SeriesName" TEXT NULL,
    "SeriesPresentationUniqueKey" TEXT NULL,
    "ShowId" TEXT NULL,
    "Size" INTEGER NULL,
    "SortName" TEXT NULL,
    "StartDate" TEXT NULL,
    "Studios" TEXT NULL,
    "Tagline" TEXT NULL,
    "Tags" TEXT NULL,
    "TopParentId" TEXT NULL,
    "TotalBitrate" INTEGER NULL,
    "Type" TEXT NOT NULL,
    "UnratedType" TEXT NULL,
    "Width" INTEGER NULL,
    CONSTRAINT "FK_BaseItems_BaseItems_ParentId" FOREIGN KEY ("ParentId") REFERENCES "BaseItems" ("Id") ON DELETE CASCADE
);
CREATE TABLE "Chapters" (
    "ItemId" TEXT NOT NULL,
    "ChapterIndex" INTEGER NOT NULL,
    "StartPositionTicks" INTEGER NOT NULL,
    "Name" TEXT NULL,
    "ImagePath" TEXT NULL,
    "ImageDateModified" TEXT NULL,
    CONSTRAINT "PK_Chapters" PRIMARY KEY ("ItemId", "ChapterIndex"),
    CONSTRAINT "FK_Chapters_BaseItems_ItemId" FOREIGN KEY ("ItemId") REFERENCES "BaseItems" ("Id") ON DELETE CASCADE
);
CREATE TABLE "CustomItemDisplayPreferences" (
    "Id" INTEGER NOT NULL CONSTRAINT "PK_CustomItemDisplayPreferences" PRIMARY KEY AUTOINCREMENT,
    "Client" TEXT NOT NULL,
    "ItemId" TEXT NOT NULL,
    "Key" TEXT NOT NULL,
    "UserId" TEXT NOT NULL,
    "Value" TEXT NULL
);
CREATE TABLE "DeviceOptions" (
    "Id" INTEGER NOT NULL CONSTRAINT "PK_DeviceOptions" PRIMARY KEY AUTOINCREMENT,
    "DeviceId" TEXT NOT NULL,
    "CustomName" TEXT NULL
);
CREATE TABLE "Devices" (
    "Id" INTEGER NOT NULL CONSTRAINT "PK_Devices" PRIMARY KEY AUTOINCREMENT,
    "UserId" TEXT NOT NULL,
    "AccessToken" TEXT NOT NULL,
    "AppName" TEXT NOT NULL,
    "AppVersion" TEXT NOT NULL,
    "DeviceName" TEXT NOT NULL,
    "DeviceId" TEXT NOT NULL,
    "IsActive" INTEGER NOT NULL,
    "DateCreated" TEXT NOT NULL,
    "DateModified" TEXT NOT NULL,
    "DateLastActivity" TEXT NOT NULL,
    CONSTRAINT "FK_Devices_Users_UserId" FOREIGN KEY ("UserId") REFERENCES "Users" ("Id") ON DELETE CASCADE
);
CREATE TABLE "DisplayPreferences" (
    "Id" INTEGER NOT NULL CONSTRAINT "PK_DisplayPreferences" PRIMARY KEY AUTOINCREMENT,
    "UserId" TEXT NOT NULL,
    "Client" TEXT NOT NULL,
    "ShowSidebar" INTEGER NOT NULL,
    "ShowBackdrop" INTEGER NOT NULL,
    "ScrollDirection" INTEGER NOT NULL,
    "IndexBy" INTEGER NULL,
    "SkipForwardLength" INTEGER NOT NULL,
    "SkipBackwardLength" INTEGER NOT NULL,
    "ChromecastVersion" INTEGER NOT NULL,
    "EnableNextVideoInfoOverlay" INTEGER NOT NULL,
    "DashboardTheme" TEXT NULL,
    "TvHome" TEXT NULL, "ItemId" TEXT NOT NULL DEFAULT '00000000-0000-0000-0000-000000000000',
    CONSTRAINT "FK_DisplayPreferences_Users_UserId" FOREIGN KEY ("UserId") REFERENCES "Users" ("Id") ON DELETE CASCADE
);
CREATE TABLE "HomeSection" (
    "Id" INTEGER NOT NULL CONSTRAINT "PK_HomeSection" PRIMARY KEY AUTOINCREMENT,
    "DisplayPreferencesId" INTEGER NOT NULL,
    "Order" INTEGER NOT NULL,
    "Type" INTEGER NOT NULL,
    CONSTRAINT "FK_HomeSection_DisplayPreferences_DisplayPreferencesId" FOREIGN KEY ("DisplayPreferencesId") REFERENCES "DisplayPreferences" ("Id") ON DELETE CASCADE
);
CREATE TABLE "ImageInfos" (
    "Id" INTEGER NOT NULL CONSTRAINT "PK_ImageInfos" PRIMARY KEY AUTOINCREMENT,
    "LastModified" TEXT NOT NULL,
    "Path" TEXT NOT NULL,
    "UserId" TEXT NULL,
    CONSTRAINT "FK_ImageInfos_Users_UserId" FOREIGN KEY ("UserId") REFERENCES "Users" ("Id") ON DELETE CASCADE
);
CREATE TABLE "ItemDisplayPreferences" (
    "Id" INTEGER NOT NULL CONSTRAINT "PK_ItemDisplayPreferences" PRIMARY KEY AUTOINCREMENT,
    "UserId" TEXT NOT NULL,
    "ItemId" TEXT NOT NULL,
    "Client" TEXT NOT NULL,
    "ViewType" INTEGER NOT NULL,
    "RememberIndexing" INTEGER NOT NULL,
    "IndexBy" INTEGER NULL,
    "RememberSorting" INTEGER NOT NULL,
    "SortBy" TEXT NOT NULL,
    "SortOrder" INTEGER NOT NULL,
    CONSTRAINT "FK_ItemDisplayPreferences_Users_UserId" FOREIGN KEY ("UserId") REFERENCES "Users" ("Id") ON DELETE CASCADE
);
CREATE TABLE "ItemValues" (
    "ItemValueId" TEXT NOT NULL CONSTRAINT "PK_ItemValues" PRIMARY KEY,
    "Type" INTEGER NOT NULL,
    "Value" TEXT NOT NULL,
    "CleanValue" TEXT NOT NULL
);
CREATE TABLE "ItemValuesMap" (
    "ItemId" TEXT NOT NULL,
    "ItemValueId" TEXT NOT NULL,
    CONSTRAINT "PK_ItemValuesMap" PRIMARY KEY ("ItemValueId", "ItemId"),
    CONSTRAINT "FK_ItemValuesMap_BaseItems_ItemId" FOREIGN KEY ("ItemId") REFERENCES "BaseItems" ("Id") ON DELETE CASCADE,
    CONSTRAINT "FK_ItemValuesMap_ItemValues_ItemValueId" FOREIGN KEY ("ItemValueId") REFERENCES "ItemValues" ("ItemValueId") ON DELETE CASCADE
);
CREATE TABLE "KeyframeData" (
    "ItemId" TEXT NOT NULL CONSTRAINT "PK_KeyframeData" PRIMARY KEY,
    "TotalDuration" INTEGER NOT NULL,
    "KeyframeTicks" TEXT NULL,
    CONSTRAINT "FK_KeyframeData_BaseItems_ItemId" FOREIGN KEY ("ItemId") REFERENCES "BaseItems" ("Id") ON DELETE CASCADE
);
CREATE TABLE "MediaSegments" (
    "Id" TEXT NOT NULL CONSTRAINT "PK_MediaSegments" PRIMARY KEY,
    "EndTicks" INTEGER NOT NULL,
    "ItemId" TEXT NOT NULL,
    "SegmentProviderId" TEXT NOT NULL,
    "StartTicks" INTEGER NOT NULL,
    "Type" INTEGER NOT NULL
);
CREATE TABLE "MediaStreamInfos" (
    "ItemId" TEXT NOT NULL,
    "StreamIndex" INTEGER NOT NULL,
    "AspectRatio" TEXT NULL,
    "AverageFrameRate" REAL NULL,
    "BitDepth" INTEGER NULL,
    "BitRate" INTEGER NULL,
    "BlPresentFlag" INTEGER NULL,
    "ChannelLayout" TEXT NULL,
    "Channels" INTEGER NULL,
    "Codec" TEXT NULL,
    "CodecTag" TEXT NULL,
    "CodecTimeBase" TEXT NULL,
    "ColorPrimaries" TEXT NULL,
    "ColorSpace" TEXT NULL,
    "ColorTransfer" TEXT NULL,
    "Comment" TEXT NULL,
    "DvBlSignalCompatibilityId" INTEGER NULL,
    "DvLevel" INTEGER NULL,
    "DvProfile" INTEGER NULL,
    "DvVersionMajor" INTEGER NULL,
    "DvVersionMinor" INTEGER NULL,
    "ElPresentFlag" INTEGER NULL,
    "Height" INTEGER NULL,
    "IsAnamorphic" INTEGER NULL,
    "IsAvc" INTEGER NULL,
    "IsDefault" INTEGER NOT NULL,
    "IsExternal" INTEGER NOT NULL,
    "IsForced" INTEGER NOT NULL,
    "IsHearingImpaired" INTEGER NULL,
    "IsInterlaced" INTEGER NULL,
    "KeyFrames" TEXT NULL,
    "Language" TEXT NULL,
    "Level" REAL NULL,
    "NalLengthSize" TEXT NULL,
    "Path" TEXT NULL,
    "PixelFormat" TEXT NULL,
    "Profile" TEXT NULL,
    "RealFrameRate" REAL NULL,
    "RefFrames" INTEGER NULL,
    "Rotation" INTEGER NULL,
    "RpuPresentFlag" INTEGER NULL,
    "SampleRate" INTEGER NULL,
    "StreamType" INTEGER NOT NULL,
    "TimeBase" TEXT NULL,
    "Title" TEXT NULL,
    "Width" INTEGER NULL, "Hdr10PlusPresentFlag" INTEGER NULL,
    CONSTRAINT "PK_MediaStreamInfos" PRIMARY KEY ("ItemId", "StreamIndex"),
    CONSTRAINT "FK_MediaStreamInfos_BaseItems_ItemId" FOREIGN KEY ("ItemId") REFERENCES "BaseItems" ("Id") ON DELETE CASCADE
);
CREATE TABLE "PeopleBaseItemMap" (
    "ItemId" TEXT NOT NULL,
    "PeopleId" TEXT NOT NULL,
    "Role" TEXT NOT NULL,
    "ListOrder" INTEGER NULL,
    "SortOrder" INTEGER NULL,
    CONSTRAINT "PK_PeopleBaseItemMap" PRIMARY KEY ("ItemId", "PeopleId", "Role"),
    CONSTRAINT "FK_PeopleBaseItemMap_BaseItems_ItemId" FOREIGN KEY ("ItemId") REFERENCES "BaseItems" ("Id") ON DELETE CASCADE,
    CONSTRAINT "FK_PeopleBaseItemMap_Peoples_PeopleId" FOREIGN KEY ("PeopleId") REFERENCES "Peoples" ("Id") ON DELETE CASCADE
);
CREATE TABLE "Peoples" (
    "Id" TEXT NOT NULL CONSTRAINT "PK_Peoples" PRIMARY KEY,
    "Name" TEXT NOT NULL,
    "PersonType" TEXT NULL
);
CREATE TABLE "Permissions" (
    "Id" INTEGER NOT NULL CONSTRAINT "PK_Permissions" PRIMARY KEY AUTOINCREMENT,
    "Kind" INTEGER NOT NULL,
    "Permission_Permissions_Guid" TEXT NULL,
    "RowVersion" INTEGER NOT NULL,
    "UserId" TEXT NULL,
    "Value" INTEGER NOT NULL,
    CONSTRAINT "FK_Permissions_Users_UserId" FOREIGN KEY ("UserId") REFERENCES "Users" ("Id") ON DELETE CASCADE
);
CREATE TABLE "Preferences" (
    "Id" INTEGER NOT NULL CONSTRAINT "PK_Preferences" PRIMARY KEY AUTOINCREMENT,
    "Kind" INTEGER NOT NULL,
    "Preference_Preferences_Guid" TEXT NULL,
    "RowVersion" INTEGER NOT NULL,
    "UserId" TEXT NULL,
    "Value" TEXT NOT NULL,
    CONSTRAINT "FK_Preferences_Users_UserId" FOREIGN KEY ("UserId") REFERENCES "Users" ("Id") ON DELETE CASCADE
);
CREATE TABLE "TrickplayInfos" (
    "ItemId" TEXT NOT NULL,
    "Width" INTEGER NOT NULL,
    "Height" INTEGER NOT NULL,
    "TileWidth" INTEGER NOT NULL,
    "TileHeight" INTEGER NOT NULL,
    "ThumbnailCount" INTEGER NOT NULL,
    "Interval" INTEGER NOT NULL,
    "Bandwidth" INTEGER NOT NULL,
    CONSTRAINT "PK_TrickplayInfos" PRIMARY KEY ("ItemId", "Width")
);
CREATE TABLE "UserData" (
    "ItemId" TEXT NOT NULL,
    "UserId" TEXT NOT NULL,
    "CustomDataKey" TEXT NOT NULL,
    "AudioStreamIndex" INTEGER NULL,
    "IsFavorite" INTEGER NOT NULL,
    "LastPlayedDate" TEXT NULL,
    "Likes" INTEGER NULL,
    "PlayCount" INTEGER NOT NULL,
    "PlaybackPositionTicks" INTEGER NOT NULL,
    "Played" INTEGER NOT NULL,
    "Rating" REAL NULL,
    "SubtitleStreamIndex" INTEGER NULL, "RetentionDate" TEXT NULL,
    CONSTRAINT "PK_UserData" PRIMARY KEY ("ItemId", "UserId", "CustomDataKey"),
    CONSTRAINT "FK_UserData_BaseItems_ItemId" FOREIGN KEY ("ItemId") REFERENCES "BaseItems" ("Id") ON DELETE CASCADE,
    CONSTRAINT "FK_UserData_Users_UserId" FOREIGN KEY ("UserId") REFERENCES "Users" ("Id") ON DELETE CASCADE
);
CREATE TABLE "Users" (
    "Id" TEXT NOT NULL CONSTRAINT "PK_Users" PRIMARY KEY,
    "AudioLanguagePreference" TEXT NULL,
    "AuthenticationProviderId" TEXT NOT NULL,
    "CastReceiverId" TEXT NULL,
    "DisplayCollectionsView" INTEGER NOT NULL,
    "DisplayMissingEpisodes" INTEGER NOT NULL,
    "EnableAutoLogin" INTEGER NOT NULL,
    "EnableLocalPassword" INTEGER NOT NULL,
    "EnableNextEpisodeAutoPlay" INTEGER NOT NULL,
    "EnableUserPreferenceAccess" INTEGER NOT NULL,
    "HidePlayedInLatest" INTEGER NOT NULL,
    "InternalId" INTEGER NOT NULL,
    "InvalidLoginAttemptCount" INTEGER NOT NULL,
    "LastActivityDate" TEXT NULL,
    "LastLoginDate" TEXT NULL,
    "LoginAttemptsBeforeLockout" INTEGER NULL,
    "MaxActiveSessions" INTEGER NOT NULL,
    "MaxParentalRatingScore" INTEGER NULL,
    "MustUpdatePassword" INTEGER NOT NULL,
    "Password" TEXT NULL,
    "PasswordResetProviderId" TEXT NOT NULL,
    "PlayDefaultAudioTrack" INTEGER NOT NULL,
    "RememberAudioSelections" INTEGER NOT NULL,
    "RememberSubtitleSelections" INTEGER NOT NULL,
    "RemoteClientBitrateLimit" INTEGER NULL,
    "RowVersion" INTEGER NOT NULL,
    "SubtitleLanguagePreference" TEXT NULL,
    "SubtitleMode" INTEGER NOT NULL,
    "SyncPlayAccess" INTEGER NOT NULL,
    "Username" TEXT NOT NULL
, "MaxParentalRatingSubScore" INTEGER NULL);
CREATE TABLE "__EFMigrationsHistory" (
    "MigrationId" TEXT NOT NULL CONSTRAINT "PK___EFMigrationsHistory" PRIMARY KEY,
    "ProductVersion" TEXT NOT NULL
);
CREATE TABLE "__EFMigrationsLock" (
    "Id" INTEGER NOT NULL CONSTRAINT "PK___EFMigrationsLock" PRIMARY KEY,
    "Timestamp" TEXT NOT NULL
);
CREATE INDEX "IX_AccessSchedules_UserId" ON "AccessSchedules" ("UserId");
CREATE INDEX "IX_ActivityLogs_DateCreated" ON "ActivityLogs" ("DateCreated");
CREATE INDEX "IX_AncestorIds_ParentItemId" ON "AncestorIds" ("ParentItemId");
CREATE UNIQUE INDEX "IX_ApiKeys_AccessToken" ON "ApiKeys" ("AccessToken");
CREATE INDEX "IX_BaseItemImageInfos_ItemId" ON "BaseItemImageInfos" ("ItemId");
CREATE INDEX "IX_BaseItemMetadataFields_ItemId" ON "BaseItemMetadataFields" ("ItemId");
CREATE INDEX "IX_BaseItemProviders_ProviderId_ProviderValue_ItemId" ON "BaseItemProviders" ("ProviderId", "ProviderValue", "ItemId");
CREATE INDEX "IX_BaseItemTrailerTypes_ItemId" ON "BaseItemTrailerTypes" ("ItemId");
CREATE INDEX "IX_BaseItems_Id_Type_IsFolder_IsVirtualItem" ON "BaseItems" ("Id", "Type", "IsFolder", "IsVirtualItem");
CREATE INDEX "IX_BaseItems_IsFolder_TopParentId_IsVirtualItem_PresentationUniqueKey_DateCreated" ON "BaseItems" ("IsFolder", "TopParentId", "IsVirtualItem", "PresentationUniqueKey", "DateCreated");
CREATE INDEX "IX_BaseItems_MediaType_TopParentId_IsVirtualItem_PresentationUniqueKey" ON "BaseItems" ("MediaType", "TopParentId", "IsVirtualItem", "PresentationUniqueKey");
CREATE INDEX "IX_BaseItems_ParentId" ON "BaseItems" ("ParentId");
CREATE INDEX "IX_BaseItems_Path" ON "BaseItems" ("Path");
CREATE INDEX "IX_BaseItems_PresentationUniqueKey" ON "BaseItems" ("PresentationUniqueKey");
CREATE INDEX "IX_BaseItems_TopParentId_Id" ON "BaseItems" ("TopParentId", "Id");
CREATE INDEX "IX_BaseItems_Type_SeriesPresentationUniqueKey_IsFolder_IsVirtualItem" ON "BaseItems" ("Type", "SeriesPresentationUniqueKey", "IsFolder", "IsVirtualItem");
CREATE INDEX "IX_BaseItems_Type_SeriesPresentationUniqueKey_PresentationUniqueKey_SortName" ON "BaseItems" ("Type", "SeriesPresentationUniqueKey", "PresentationUniqueKey", "SortName");
CREATE INDEX "IX_BaseItems_Type_TopParentId_Id" ON "BaseItems" ("Type", "TopParentId", "Id");
CREATE INDEX "IX_BaseItems_Type_TopParentId_IsVirtualItem_PresentationUniqueKey_DateCreated" ON "BaseItems" ("Type", "TopParentId", "IsVirtualItem", "PresentationUniqueKey", "DateCreated");
CREATE INDEX "IX_BaseItems_Type_TopParentId_PresentationUniqueKey" ON "BaseItems" ("Type", "TopParentId", "PresentationUniqueKey");
CREATE INDEX "IX_BaseItems_Type_TopParentId_StartDate" ON "BaseItems" ("Type", "TopParentId", "StartDate");
CREATE INDEX "IX_CustomItemDisplayPreferences_UserId" ON "CustomItemDisplayPreferences" ("UserId");
CREATE UNIQUE INDEX "IX_CustomItemDisplayPreferences_UserId_ItemId_Client_Key" ON "CustomItemDisplayPreferences" ("UserId", "ItemId", "Client", "Key");
CREATE UNIQUE INDEX "IX_DeviceOptions_DeviceId" ON "DeviceOptions" ("DeviceId");
CREATE INDEX "IX_Devices_AccessToken_DateLastActivity" ON "Devices" ("AccessToken", "DateLastActivity");
CREATE INDEX "IX_Devices_DeviceId" ON "Devices" ("DeviceId");
CREATE INDEX "IX_Devices_DeviceId_DateLastActivity" ON "Devices" ("DeviceId", "DateLastActivity");
CREATE INDEX "IX_Devices_UserId_DeviceId" ON "Devices" ("UserId", "DeviceId");
CREATE UNIQUE INDEX "IX_DisplayPreferences_UserId_ItemId_Client" ON "DisplayPreferences" ("UserId", "ItemId", "Client");
CREATE INDEX "IX_HomeSection_DisplayPreferencesId" ON "HomeSection" ("DisplayPreferencesId");
CREATE UNIQUE INDEX "IX_ImageInfos_UserId" ON "ImageInfos" ("UserId");
CREATE INDEX "IX_ItemDisplayPreferences_UserId" ON "ItemDisplayPreferences" ("UserId");
CREATE INDEX "IX_ItemValuesMap_ItemId" ON "ItemValuesMap" ("ItemId");
CREATE INDEX "IX_ItemValues_Type_CleanValue" ON "ItemValues" ("Type", "CleanValue");
CREATE UNIQUE INDEX "IX_ItemValues_Type_Value" ON "ItemValues" ("Type", "Value");
CREATE INDEX "IX_MediaStreamInfos_StreamIndex" ON "MediaStreamInfos" ("StreamIndex");
CREATE INDEX "IX_MediaStreamInfos_StreamIndex_StreamType" ON "MediaStreamInfos" ("StreamIndex", "StreamType");
CREATE INDEX "IX_MediaStreamInfos_StreamIndex_StreamType_Language" ON "MediaStreamInfos" ("StreamIndex", "StreamType", "Language");
CREATE INDEX "IX_MediaStreamInfos_StreamType" ON "MediaStreamInfos" ("StreamType");
CREATE INDEX "IX_PeopleBaseItemMap_ItemId_ListOrder" ON "PeopleBaseItemMap" ("ItemId", "ListOrder");
CREATE INDEX "IX_PeopleBaseItemMap_ItemId_SortOrder" ON "PeopleBaseItemMap" ("ItemId", "SortOrder");
CREATE INDEX "IX_PeopleBaseItemMap_PeopleId" ON "PeopleBaseItemMap" ("PeopleId");
CREATE INDEX "IX_Peoples_Name" ON "Peoples" ("Name");
CREATE UNIQUE INDEX "IX_Permissions_UserId_Kind" ON "Permissions" ("UserId", "Kind") WHERE [UserId] IS NOT NULL;
CREATE UNIQUE INDEX "IX_Preferences_UserId_Kind" ON "Preferences" ("UserId", "Kind") WHERE [UserId] IS NOT NULL;
CREATE INDEX "IX_UserData_ItemId_UserId_IsFavorite" ON "UserData" ("ItemId", "UserId", "IsFavorite");
CREATE INDEX "IX_UserData_ItemId_UserId_LastPlayedDate" ON "UserData" ("ItemId", "UserId", "LastPlayedDate");
CREATE INDEX "IX_UserData_ItemId_UserId_PlaybackPositionTicks" ON "UserData" ("ItemId", "UserId", "PlaybackPositionTicks");
CREATE INDEX "IX_UserData_ItemId_UserId_Played" ON "UserData" ("ItemId", "UserId", "Played");
CREATE INDEX "IX_UserData_UserId" ON "UserData" ("UserId");
CREATE UNIQUE INDEX "IX_Users_Username" ON "Users" ("Username");
INSERT INTO __EFMigrationsHistory VALUES ('20200514181226_AddActivityLog','9.0.11');
INSERT INTO __EFMigrationsHistory VALUES ('20200613202153_AddUsers','9.0.11');
INSERT INTO __EFMigrationsHistory VALUES ('20200728005145_AddDisplayPreferences','9.0.11');
INSERT INTO __EFMigrationsHistory VALUES ('20200905220533_FixDisplayPreferencesIndex','9.0.11');
INSERT INTO __EFMigrationsHistory VALUES ('20201004171403_AddMaxActiveSessions','9.0.11');
INSERT INTO __EFMigrationsHistory VALUES ('20201204223655_AddCustomDisplayPreferences','9.0.11');
INSERT INTO __EFMigrationsHistory VALUES ('20210320181425_AddIndexesAndCollations','9.0.11');
INSERT INTO __EFMigrationsHistory VALUES ('20210407110544_NullableCustomPrefValue','9.0.11');
INSERT INTO __EFMigrationsHistory VALUES ('20210814002109_AddDevices','9.0.11');
INSERT INTO __EFMigrationsHistory VALUES ('20221022080052_AddIndexActivityLogsDateCreated','9.0.11');
INSERT INTO __EFMigrationsHistory VALUES ('20230526173516_RemoveEasyPassword','9.0.11');
INSERT INTO __EFMigrationsHistory VALUES ('20230626233818_AddTrickplayInfos','9.0.11');
INSERT INTO __EFMigrationsHistory VALUES ('20230923170422_UserCastReceiver','9.0.11');
INSERT INTO __EFMigrationsHistory VALUES ('20240729140605_AddMediaSegments','9.0.11');
INSERT INTO __EFMigrationsHistory VALUES ('20240928082930_MarkSegmentProviderIdNonNullable','9.0.11');
INSERT INTO __EFMigrationsHistory VALUES ('20241020103111_LibraryDbMigration','9.0.11');
INSERT INTO __EFMigrationsHistory VALUES ('20241111131257_AddedCustomDataKey','9.0.11');
INSERT INTO __EFMigrationsHistory VALUES ('20241111135439_AddedCustomDataKeyKey','9.0.11');
INSERT INTO __EFMigrationsHistory VALUES ('20241112152323_FixAncestorIdConfig','9.0.11');
INSERT INTO __EFMigrationsHistory VALUES ('20241112232041_FixMediaStreams','9.0.11');
INSERT INTO __EFMigrationsHistory VALUES ('20241112234144_FixMediaStreams2','9.0.11');
INSERT INTO __EFMigrationsHistory VALUES ('20241113133548_EnforceUniqueItemValue','9.0.11');
INSERT INTO __EFMigrationsHistory VALUES ('20250202021306_FixedCollation','9.0.11');
INSERT INTO __EFMigrationsHistory VALUES ('20250204092455_MakeStartEndDateNullable','9.0.11');
INSERT INTO __EFMigrationsHistory VALUES ('20250214031148_ChannelIdGuid','9.0.11');
INSERT INTO __EFMigrationsHistory VALUES ('20250326065026_AddInheritedParentalRatingSubValue','9.0.11');
INSERT INTO __EFMigrationsHistory VALUES ('20250327101120_AddKeyframeData','9.0.11');
INSERT INTO __EFMigrationsHistory VALUES ('20250327171413_AddHdr10PlusFlag','9.0.11');
INSERT INTO __EFMigrationsHistory VALUES ('20250331182844_FixAttachmentMigration','9.0.11');
INSERT INTO __EFMigrationsHistory VALUES ('20250401142247_FixAncestors','9.0.11');
INSERT INTO __EFMigrationsHistory VALUES ('20250405075612_FixItemValuesIndices','9.0.11');
INSERT INTO __EFMigrationsHistory VALUES ('20250420000000_CreateNetworkConfiguration','10.11.8.0');
INSERT INTO __EFMigrationsHistory VALUES ('20250420010000_MigrateNetworkConfiguration','10.11.8.0');
INSERT INTO __EFMigrationsHistory VALUES ('20250420020000_MigrateMusicBrainzTimeout','10.11.8.0');
INSERT INTO __EFMigrationsHistory VALUES ('20250420030000_MigrateEncodingOptions','10.11.8.0');
INSERT INTO __EFMigrationsHistory VALUES ('20250420040000_RenameEnableGroupingIntoCollections','10.11.8.0');
INSERT INTO __EFMigrationsHistory VALUES ('20250420050000_DisableTranscodingThrottling','10.11.8.0');
INSERT INTO __EFMigrationsHistory VALUES ('20250420060000_CreateUserLoggingConfigFile','10.11.8.0');
INSERT INTO __EFMigrationsHistory VALUES ('20250420070000_MigrateActivityLogDb','10.11.8.0');
INSERT INTO __EFMigrationsHistory VALUES ('20250420080000_RemoveDuplicateExtras','10.11.8.0');
INSERT INTO __EFMigrationsHistory VALUES ('20250420090000_AddDefaultPluginRepository','10.11.8.0');
INSERT INTO __EFMigrationsHistory VALUES ('20250420100000_MigrateUserDb','10.11.8.0');
INSERT INTO __EFMigrationsHistory VALUES ('20250420110000_ReaddDefaultPluginRepository','10.11.8.0');
INSERT INTO __EFMigrationsHistory VALUES ('20250420120000_MigrateDisplayPreferencesDb','10.11.8.0');
INSERT INTO __EFMigrationsHistory VALUES ('20250420130000_RemoveDownloadImagesInAdvance','10.11.8.0');
INSERT INTO __EFMigrationsHistory VALUES ('20250420140000_MigrateAuthenticationDb','10.11.8.0');
INSERT INTO __EFMigrationsHistory VALUES ('20250420150000_FixPlaylistOwner','10.11.8.0');
INSERT INTO __EFMigrationsHistory VALUES ('20250420160000_AddDefaultCastReceivers','10.11.8.0');
INSERT INTO __EFMigrationsHistory VALUES ('20250420170000_UpdateDefaultPluginRepository','10.11.8.0');
INSERT INTO __EFMigrationsHistory VALUES ('20250420180000_FixAudioData','10.11.8.0');
INSERT INTO __EFMigrationsHistory VALUES ('20250420190000_RemoveDuplicatePlaylistChildren','10.11.8.0');
INSERT INTO __EFMigrationsHistory VALUES ('20250420193000_MigrateLibraryDbCompatibilityCheck','10.11.8.0');
INSERT INTO __EFMigrationsHistory VALUES ('20250420200000_MigrateLibraryDb','10.11.8.0');
INSERT INTO __EFMigrationsHistory VALUES ('20250420210000_MoveExtractedFiles','10.11.8.0');
INSERT INTO __EFMigrationsHistory VALUES ('20250420220000_MigrateRatingLevels','10.11.8.0');
INSERT INTO __EFMigrationsHistory VALUES ('20250420230000_MoveTrickplayFiles','10.11.8.0');
INSERT INTO __EFMigrationsHistory VALUES ('20250420230000_RefreshInternalDateModified','10.11.8.0');
INSERT INTO __EFMigrationsHistory VALUES ('20250421000000_MigrateKeyframeData','10.11.8.0');
INSERT INTO __EFMigrationsHistory VALUES ('20250609115616_DetachUserDataInsteadOfDelete','9.0.11');
INSERT INTO __EFMigrationsHistory VALUES ('20250618010000_MigrateLibraryUserData','10.11.8.0');
INSERT INTO __EFMigrationsHistory VALUES ('20250620180000_FixDates','10.11.8.0');
INSERT INTO __EFMigrationsHistory VALUES ('20250622170802_BaseItemImageInfoDateModifiedNullable','9.0.11');
INSERT INTO __EFMigrationsHistory VALUES ('20250714044826_ResetJournalMode','9.0.11');
INSERT INTO __EFMigrationsHistory VALUES ('20250730215000_ReseedFolderFlag','10.11.8.0');
INSERT INTO __EFMigrationsHistory VALUES ('20250913211637_AddProperParentChildRelationBaseItemWithCascade','9.0.11');
INSERT INTO __EFMigrationsHistory VALUES ('20250925203415_ExtendPeopleMapKey','9.0.11');
INSERT INTO __EFMigrationsHistory VALUES ('20251009200000_CleanMusicArtist','10.11.8.0');
INSERT INTO __EFMigrationsHistory VALUES ('20260206200000_FixLibrarySubtitleDownloadLanguages','10.11.8.0');
